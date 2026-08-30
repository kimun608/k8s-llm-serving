#!/usr/bin/env python3
"""Validate and compare controlled Windows CPU8 serving-factor experiments."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from analyze import aggregate as aggregate_raw
from analyze import nice_max
from compare_windows_sequential import (
    CONCURRENCIES,
    EXPECTED_ENV,
    IMAGE,
    KV_512_BYTES,
    KV_768_BYTES,
    REQUESTS_PER_PHASE,
    WARMUP_REQUESTS,
    ComparisonError,
    StageSpec,
    comparable,
    expected_args,
    expected_resources,
    finite,
    fmt,
    model_signature,
    normalize_env,
    normalized_config,
    parse_timestamp,
    percent_change,
    read_json,
    read_jsonl,
    request_signature,
    require_finite,
    resolve_phase_artifact,
    validate_expected_workload,
    validate_phase_pod,
    warmup_signature,
    write_csv,
)


BASELINE = StageSpec(
    0,
    "baseline-cpu8",
    "CPU8 baseline",
    8,
    False,
    KV_512_BYTES,
    "auto (BF16)",
    None,
    "reference",
)
MTP_ONLY = StageSpec(
    1,
    "mtp-cpu8",
    "MTP2 only",
    8,
    True,
    KV_512_BYTES,
    "auto (BF16)",
    BASELINE.name,
    "MTP off→MTP2",
)
KV768_ONLY = StageSpec(
    2,
    "baseline-kv768-cpu8",
    "KV768 only",
    8,
    False,
    KV_768_BYTES,
    "auto (BF16)",
    BASELINE.name,
    "KV budget 512→768MiB",
)
FP8_ONLY = StageSpec(
    3,
    "baseline-cpu8-fp8",
    "FP8 KV only",
    8,
    False,
    KV_512_BYTES,
    "fp8",
    BASELINE.name,
    "KV dtype BF16→FP8",
)
COMBO = StageSpec(
    4,
    "baseline-kv768-fp8-cpu8",
    "KV768 + FP8 KV",
    8,
    False,
    KV_768_BYTES,
    "fp8",
    BASELINE.name,
    "KV768 + FP8",
)
CORE_STAGES = (BASELINE, MTP_ONLY, KV768_ONLY, FP8_ONLY)
COLORS = {
    BASELINE.name: "#1d4ed8",
    MTP_ONLY.name: "#7c3aed",
    KV768_ONLY.name: "#059669",
    FP8_ONLY.name: "#ea580c",
    COMBO.name: "#be123c",
}


def active_stages(results_root: Path) -> tuple[StageSpec, ...]:
    combo_dir = results_root / COMBO.name
    if not combo_dir.exists():
        return CORE_STAGES
    if not combo_dir.is_dir():
        raise ComparisonError(f"optional combo path is not a directory: {combo_dir}")
    contents = list(combo_dir.iterdir())
    if not contents:
        raise ComparisonError(
            f"optional combo directory is empty; remove it or complete the run: {combo_dir}"
        )
    return (*CORE_STAGES, COMBO)


def require_result_files(results_root: Path, stages: tuple[StageSpec, ...]) -> None:
    missing: list[str] = []
    for stage in stages:
        directory = results_root / stage.name
        absent = [
            filename
            for filename in ("summary.json", "run-manifest.json")
            if not (directory / filename).is_file()
        ]
        if absent:
            missing.append(f"  - {stage.name}: {', '.join(absent)} under {directory}")
    if missing:
        raise ComparisonError(
            "Missing required CPU8 factor result(s):\n"
            + "\n".join(missing)
            + "\nAll four core seven-phase/700-request stages must be complete."
        )


def load_results(
    results_root: Path, stages: tuple[StageSpec, ...]
) -> dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Load each saved summary only after reproducing it from raw artifacts."""
    require_result_files(results_root, stages)
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    for stage in stages:
        directory = results_root / stage.name
        summary = read_json(directory / "summary.json")
        manifest = read_json(directory / "run-manifest.json")
        if not isinstance(summary, list) or not isinstance(manifest, dict):
            raise ComparisonError(f"{stage.name}: malformed summary or manifest")
        recomputed_summary, recomputed_manifest = aggregate_raw(directory)
        if recomputed_manifest != manifest:
            raise ComparisonError(f"{stage.name}: raw aggregator read another manifest")
        if comparable(summary) != comparable(recomputed_summary):
            raise ComparisonError(
                f"{stage.name}: summary.json differs from raw request/metric aggregation"
            )
        loaded[stage.name] = (
            sorted(summary, key=lambda row: int(row["concurrency"])),
            manifest,
        )
    return loaded


def validate_suite_manifest(
    results_root: Path,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    """Bind every formal artifact to the frozen multi-invocation suite provenance."""
    path = results_root / "suite-manifest.json"
    if not path.is_file():
        raise ComparisonError(f"suite manifest is missing: {path}")
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        raise ComparisonError("suite-manifest.json is not an object")
    if manifest.get("schema_version") != 1:
        raise ComparisonError("suite manifest schema_version must be 1")
    if manifest.get("status") not in {"running", "completed"}:
        raise ComparisonError("suite manifest status must be running or completed")
    variants = manifest.get("variants")
    if not isinstance(variants, list) or any(not isinstance(item, str) for item in variants):
        raise ComparisonError("suite manifest variants are malformed")
    expected_variants = set(loaded)
    missing_variants = sorted(expected_variants.difference(variants))
    if missing_variants:
        raise ComparisonError(
            f"suite manifest does not cover active result variants: {missing_variants}"
        )
    fingerprint = manifest.get("source_fingerprint")
    runner_hash = manifest.get("benchmark_runner_sha256")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9A-Fa-f]{64}", fingerprint):
        raise ComparisonError("suite source_fingerprint is malformed")
    if not isinstance(runner_hash, str) or not re.fullmatch(r"[0-9A-Fa-f]{64}", runner_hash):
        raise ComparisonError("suite benchmark_runner_sha256 is malformed")

    baseline_manifest = loaded[BASELINE.name][1]
    baseline_environment = baseline_manifest.get("environment", {})
    baseline_docker = baseline_environment.get("docker", {})
    expected_docker_fingerprint = "|".join(
        str(baseline_docker.get(key))
        for key in ("cpus", "memory_bytes", "architecture", "server_version")
    )
    if runner_hash.lower() != str(baseline_manifest.get("runner_sha256", "")).lower():
        raise ComparisonError("suite and formal benchmark runner hashes differ")
    if manifest.get("docker_fingerprint") != expected_docker_fingerprint:
        raise ComparisonError("suite and formal Docker fingerprints differ")
    if manifest.get("git_commit") != baseline_environment.get("git", {}).get("commit"):
        raise ComparisonError("suite and formal Git commits differ")

    suite_start = parse_timestamp(manifest.get("started_at"), "suite start")
    suite_finish: datetime | None = None
    if manifest.get("status") == "completed":
        suite_finish = parse_timestamp(manifest.get("finished_at"), "suite finish")
        if suite_finish <= suite_start:
            raise ComparisonError("suite finish does not follow suite start")
    elif manifest.get("finished_at") not in (None, ""):
        raise ComparisonError("running suite must not have a finished_at timestamp")

    invocations = manifest.get("invocations")
    if not isinstance(invocations, list) or not invocations:
        raise ComparisonError("suite manifest invocations are missing")
    previous_finish: datetime | None = None
    covered_variants: set[str] = set()
    for index, invocation in enumerate(invocations):
        if not isinstance(invocation, dict):
            raise ComparisonError(f"suite invocation {index} is malformed")
        status = invocation.get("status")
        if status not in {"running", "completed"}:
            raise ComparisonError(f"suite invocation {index} has invalid status")
        invocation_variants = invocation.get("variants")
        if not isinstance(invocation_variants, list) or not invocation_variants or any(
            not isinstance(item, str) for item in invocation_variants
        ):
            raise ComparisonError(f"suite invocation {index} variants are malformed")
        covered_variants.update(invocation_variants)
        started = parse_timestamp(invocation.get("started_at"), f"invocation {index} start")
        if started < suite_start or (previous_finish is not None and started < previous_finish):
            raise ComparisonError(f"suite invocation {index} is out of chronological order")
        if status == "completed":
            finished = parse_timestamp(
                invocation.get("finished_at"), f"invocation {index} finish"
            )
            if finished <= started:
                raise ComparisonError(f"suite invocation {index} finish is invalid")
            previous_finish = finished
        else:
            if index != len(invocations) - 1 or invocation.get("finished_at") not in (
                None,
                "",
            ):
                raise ComparisonError("only the final suite invocation may be running")
    missing_invocation_variants = sorted(expected_variants.difference(covered_variants))
    if missing_invocation_variants:
        raise ComparisonError(
            "suite invocations do not cover active result variants: "
            f"{missing_invocation_variants}"
        )
    if manifest.get("status") != invocations[-1].get("status"):
        raise ComparisonError("suite and final invocation statuses differ")
    if suite_finish is not None and previous_finish != suite_finish:
        raise ComparisonError("suite and final invocation finish timestamps differ")
    return manifest


def validate_container(stage: StageSpec, manifest: dict[str, Any]) -> dict[str, Any]:
    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        raise ComparisonError(f"{stage.name}: environment capture is missing")
    host = environment.get("host")
    docker = environment.get("docker")
    kubernetes = environment.get("kubernetes")
    if not isinstance(host, dict) or not isinstance(docker, dict) or not isinstance(
        kubernetes, dict
    ):
        raise ComparisonError(f"{stage.name}: host/Docker/Kubernetes capture is incomplete")
    if not str(host.get("platform", "")).startswith("Windows-"):
        raise ComparisonError(f"{stage.name}: host platform is not Windows")
    if str(host.get("machine", "")).upper() not in {"AMD64", "X86_64"}:
        raise ComparisonError(f"{stage.name}: host machine is not x86_64")
    if docker.get("architecture") != "x86_64":
        raise ComparisonError(f"{stage.name}: Docker architecture is not x86_64")
    if not str(docker.get("operating_system", "")).startswith("Docker Desktop"):
        raise ComparisonError(f"{stage.name}: Docker Desktop identity is missing")

    nodes = kubernetes.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ComparisonError(f"{stage.name}: Kubernetes node inventory is empty")
    if any(
        not isinstance(node, dict) or node.get("architecture") != "amd64"
        for node in nodes
    ):
        raise ComparisonError(f"{stage.name}: every Kubernetes node must be amd64")

    container = kubernetes.get("container")
    if not isinstance(container, dict):
        raise ComparisonError(f"{stage.name}: captured container spec is missing")
    if container.get("image") != IMAGE:
        raise ComparisonError(
            f"{stage.name}: expected image {IMAGE!r}, found {container.get('image')!r}"
        )
    exact_args = expected_args(stage)
    if container.get("args") != exact_args:
        raise ComparisonError(
            f"{stage.name}: container args differ; "
            f"expected={exact_args!r}, found={container.get('args')!r}"
        )
    exact_resources = expected_resources(stage)
    if container.get("resources") != exact_resources:
        raise ComparisonError(
            f"{stage.name}: resources differ; "
            f"expected={exact_resources!r}, found={container.get('resources')!r}"
        )
    if normalize_env(container.get("env"), stage.name) != EXPECTED_ENV:
        raise ComparisonError(f"{stage.name}: serving environment variables differ")
    if kubernetes.get("serving_variant") != stage.name:
        raise ComparisonError(f"{stage.name}: serving-variant label differs")
    if environment.get("serving_metadata_scope") != "local-kubernetes":
        raise ComparisonError(f"{stage.name}: serving metadata is not local Kubernetes")

    pods = kubernetes.get("pods")
    if not isinstance(pods, list) or len(pods) != 1 or not isinstance(pods[0], dict):
        raise ComparisonError(f"{stage.name}: expected exactly one captured Pod")
    pod = pods[0]
    for field in ("name", "uid", "node", "image_id"):
        if not pod.get(field):
            raise ComparisonError(f"{stage.name}: captured Pod lacks {field}")
    if pod.get("phase") != "Running" or int(pod.get("restart_count", -1)) != 0:
        raise ComparisonError(f"{stage.name}: Pod is not Running with restart_count=0")
    return pod


def validate_response_fields(rows: list[dict[str, Any]], label: str) -> None:
    for index, request in enumerate(rows):
        content_hash = request.get("content_sha256")
        if not isinstance(content_hash, str) or len(content_hash) != 64:
            raise ComparisonError(f"{label}: request {index} content hash is malformed")
        prompt_tokens = int(request.get("prompt_tokens", -1))
        completion_tokens = int(request.get("completion_tokens", -1))
        if int(request.get("total_tokens", -1)) != prompt_tokens + completion_tokens:
            raise ComparisonError(f"{label}: request {index} total token count differs")
        if int(request.get("content_chunks", -1)) < 1 or int(
            request.get("content_chars", -1)
        ) < 0:
            raise ComparisonError(f"{label}: request {index} content capture is invalid")


def validate_speculative_counters(
    stage: StageSpec, row: dict[str, Any], label: str
) -> None:
    counter_names = (
        "spec_drafts_delta",
        "spec_draft_tokens_delta",
        "spec_accepted_tokens_delta",
    )
    if stage.mtp_enabled:
        drafts = require_finite(row.get(counter_names[0]), f"{label} drafts")
        draft_tokens = require_finite(row.get(counter_names[1]), f"{label} draft tokens")
        accepted = require_finite(row.get(counter_names[2]), f"{label} accepted tokens")
        acceptance = require_finite(
            row.get("spec_acceptance_percent"), f"{label} acceptance"
        )
        if (
            drafts <= 0
            or draft_tokens <= 0
            or accepted < 0
            or accepted > draft_tokens
            or not 0 <= acceptance <= 100
        ):
            raise ComparisonError(f"{label}: MTP counters are invalid")
        return

    for name in (*counter_names, "spec_acceptance_percent"):
        value = finite(row.get(name))
        if math.isfinite(value) and value != 0:
            raise ComparisonError(f"{label}: {name} must be zero/absent with MTP off")


def validate_results(
    results_root: Path,
    stages: tuple[StageSpec, ...],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    baseline_rows, baseline_manifest = loaded[BASELINE.name]
    baseline_config = normalized_config(baseline_manifest.get("config"))
    validate_expected_workload(baseline_config, BASELINE.name)
    prompt_hash = baseline_manifest.get("prompts_sha256")
    prompts_file = baseline_manifest.get("prompts_file")
    token_validation = baseline_manifest.get("input_token_validation")
    server_version = baseline_manifest.get("server_version")
    model = model_signature(baseline_manifest.get("model_endpoint"))
    baseline_environment = baseline_manifest.get("environment")
    if not isinstance(baseline_environment, dict):
        raise ComparisonError(f"{BASELINE.name}: environment is missing")
    host = baseline_environment.get("host")
    docker = baseline_environment.get("docker")
    nodes = baseline_environment.get("kubernetes", {}).get("nodes")
    git = baseline_environment.get("git")
    runner_hash = baseline_manifest.get("runner_sha256")
    schema = baseline_manifest.get("schema_version")
    if schema != 1:
        raise ComparisonError(f"{BASELINE.name}: schema_version must be 1")
    if not isinstance(prompt_hash, str) or len(prompt_hash) != 64:
        raise ComparisonError(f"{BASELINE.name}: prompts SHA-256 is malformed")
    if not isinstance(token_validation, dict) or not token_validation:
        raise ComparisonError(f"{BASELINE.name}: token validation is missing")
    if not isinstance(server_version, dict) or not server_version or not model:
        raise ComparisonError(f"{BASELINE.name}: model/server identity is missing")
    if not isinstance(git, dict) or not git.get("commit"):
        raise ComparisonError(f"{BASELINE.name}: Git provenance is missing")
    if not isinstance(runner_hash, str) or len(runner_hash) != 64:
        raise ComparisonError(f"{BASELINE.name}: runner SHA-256 is malformed")

    baseline_pod = validate_container(BASELINE, baseline_manifest)
    canonical_requests: tuple[tuple[Any, ...], ...] | None = None
    canonical_warmups: tuple[tuple[Any, ...], ...] | None = None
    pods: dict[str, dict[str, Any]] = {}
    stage_times: dict[str, tuple[datetime, datetime]] = {}
    warnings: list[str] = []
    pod_uids: set[str] = set()
    previous_stage_finish: datetime | None = None

    for stage in stages:
        rows, manifest = loaded[stage.name]
        if manifest.get("schema_version") != schema:
            raise ComparisonError(f"{stage.name}: schema version differs")
        if manifest.get("status") != "completed" or int(
            manifest.get("total_failures", -1)
        ) != 0:
            raise ComparisonError(f"{stage.name}: run is not completed with zero failures")
        if manifest.get("base_url") != baseline_manifest.get("base_url"):
            raise ComparisonError(f"{stage.name}: benchmark endpoint differs")
        if manifest.get("endpoint_binding") != "local-kubernetes-service":
            raise ComparisonError(f"{stage.name}: endpoint is not local Kubernetes")

        config = manifest.get("config")
        if not isinstance(config, dict) or config.get("experiment") != stage.name:
            raise ComparisonError(f"{stage.name}: config experiment identity differs")
        validate_expected_workload(config, stage.name)
        if normalized_config(config) != baseline_config:
            raise ComparisonError(f"{stage.name}: workload config differs from baseline")
        if manifest.get("concurrencies") != list(CONCURRENCIES):
            raise ComparisonError(f"{stage.name}: concurrency order differs")
        if int(manifest.get("prompt_count", -1)) != REQUESTS_PER_PHASE:
            raise ComparisonError(f"{stage.name}: prompt_count must be 100")
        if manifest.get("prompts_sha256") != prompt_hash:
            raise ComparisonError(f"{stage.name}: prompt workload SHA-256 differs")
        if manifest.get("prompts_file") != prompts_file:
            raise ComparisonError(f"{stage.name}: prompts file provenance differs")
        if manifest.get("input_token_validation") != token_validation:
            raise ComparisonError(f"{stage.name}: tokenized input workload differs")
        if manifest.get("server_version") != server_version:
            raise ComparisonError(f"{stage.name}: vLLM server version differs")
        if model_signature(manifest.get("model_endpoint")) != model:
            raise ComparisonError(f"{stage.name}: served model identity differs")
        if manifest.get("runner_sha256") != runner_hash:
            raise ComparisonError(f"{stage.name}: benchmark runner differs")

        environment = manifest.get("environment")
        if not isinstance(environment, dict):
            raise ComparisonError(f"{stage.name}: environment is missing")
        if environment.get("host") != host:
            raise ComparisonError(f"{stage.name}: host identity/resources differ")
        if environment.get("docker") != docker:
            raise ComparisonError(f"{stage.name}: Docker identity/resources differ")
        if environment.get("git") != git:
            raise ComparisonError(f"{stage.name}: Git commit or worktree state differs")
        if environment.get("kubernetes", {}).get("nodes") != nodes:
            raise ComparisonError(f"{stage.name}: Kubernetes node inventory differs")

        pod = baseline_pod if stage is BASELINE else validate_container(stage, manifest)
        pods[stage.name] = pod
        if pod["image_id"] != baseline_pod["image_id"]:
            raise ComparisonError(f"{stage.name}: immutable image ID differs")
        if pod["node"] != baseline_pod["node"]:
            raise ComparisonError(f"{stage.name}: serving Pod moved to another node")
        if pod["uid"] in pod_uids:
            raise ComparisonError(f"{stage.name}: Pod UID was reused across formal stages")
        pod_uids.add(pod["uid"])

        stage_start = parse_timestamp(manifest.get("started_at_utc"), f"{stage.name} start")
        stage_finish = parse_timestamp(
            manifest.get("finished_at_utc"), f"{stage.name} finish"
        )
        if stage_finish <= stage_start:
            raise ComparisonError(f"{stage.name}: run finish does not follow start")
        if previous_stage_finish is not None and stage_start < previous_stage_finish:
            raise ComparisonError(f"{stage.name}: formal runs overlap or are out of order")
        stage_times[stage.name] = (stage_start, stage_finish)
        previous_stage_finish = stage_finish

        if [int(row.get("concurrency", -1)) for row in rows] != list(CONCURRENCIES):
            raise ComparisonError(f"{stage.name}: summary needs seven ordered phases")
        phases = manifest.get("phases")
        if not isinstance(phases, list) or [
            int(phase.get("concurrency", -1)) if isinstance(phase, dict) else -1
            for phase in phases
        ] != list(CONCURRENCIES):
            raise ComparisonError(f"{stage.name}: manifest needs seven ordered phases")

        stage_dir = results_root / stage.name
        previous_phase_finish: datetime | None = None
        total_requests = 0
        for row, phase, concurrency in zip(rows, phases, CONCURRENCIES, strict=True):
            assert isinstance(phase, dict)
            label = f"{stage.name} C={concurrency}"
            counts = (
                int(row.get("requests", -1)),
                int(row.get("successes", -1)),
                int(row.get("failures", -1)),
            )
            total_requests += counts[0]
            if counts != (100, 100, 0):
                raise ComparisonError(f"{label}: result counts are not 100/100/0")
            if (
                int(phase.get("request_count", -1)),
                int(phase.get("success_count", -1)),
                int(phase.get("failure_count", -1)),
            ) != (100, 100, 0):
                raise ComparisonError(f"{label}: phase counts are not 100/100/0")
            if phase.get("metrics_scrape_errors") != []:
                raise ComparisonError(f"{label}: metrics scrape errors are present")
            if phase.get("runtime_validation_errors") != []:
                raise ComparisonError(f"{label}: runtime validation errors are present")
            if int(phase.get("warmup_request_count", -1)) != WARMUP_REQUESTS:
                raise ComparisonError(f"{label}: warmup count is not three")
            if int(phase.get("metrics_sample_count", 0)) < 2:
                raise ComparisonError(f"{label}: fewer than two metric samples")
            validate_phase_pod(stage, phase, pod, concurrency)

            raw_phase_path = stage_dir / "raw" / f"phase-c{concurrency:02d}.json"
            if not raw_phase_path.is_file() or read_json(raw_phase_path) != phase:
                raise ComparisonError(f"{label}: raw phase differs or is missing")
            phase_start = parse_timestamp(phase.get("started_at_utc"), f"{label} start")
            phase_finish = parse_timestamp(
                phase.get("finished_at_utc"), f"{label} finish"
            )
            duration = require_finite(
                phase.get("duration_seconds"), f"{label} duration", positive=True
            )
            wall_seconds = (phase_finish - phase_start).total_seconds()
            if wall_seconds <= 0 or abs(wall_seconds - duration) > max(
                5.0, duration * 0.01
            ):
                raise ComparisonError(f"{label}: wall/monotonic timer validation failed")
            if phase_start < stage_start or phase_finish > stage_finish:
                raise ComparisonError(f"{label}: phase falls outside its run")
            if previous_phase_finish is not None and phase_start < previous_phase_finish:
                raise ComparisonError(f"{label}: phases overlap or are out of order")
            previous_phase_finish = phase_finish

            requests_path = resolve_phase_artifact(
                stage_dir, phase.get("requests_file"), f"{label} requests"
            )
            metrics_path = resolve_phase_artifact(
                stage_dir, phase.get("metrics_file"), f"{label} metrics"
            )
            requests = read_jsonl(requests_path)
            if any(int(item.get("concurrency", -1)) != concurrency for item in requests):
                raise ComparisonError(f"{label}: raw request concurrency differs")
            signature = request_signature(requests, label)
            validate_response_fields(requests, label)
            if canonical_requests is None:
                canonical_requests = signature
            elif signature != canonical_requests:
                raise ComparisonError(f"{label}: raw prompt/token/order workload differs")
            warmups = warmup_signature(phase.get("warmup_results"), concurrency, label)
            if canonical_warmups is None:
                canonical_warmups = warmups
            elif warmups != canonical_warmups:
                raise ComparisonError(f"{label}: warmup prompt/token/order differs")

            prompt_total = sum(int(item[3]) for item in signature)
            completion_total = sum(int(item[4]) for item in signature)
            totals = (
                int(require_finite(row.get("total_prompt_tokens"), f"{label} prompt")),
                int(
                    require_finite(
                        row.get("total_completion_tokens"), f"{label} completion"
                    )
                ),
                int(
                    require_finite(
                        row.get("server_prompt_tokens_delta"), f"{label} server prompt"
                    )
                ),
                int(
                    require_finite(
                        row.get("server_generation_tokens_delta"),
                        f"{label} server completion",
                    )
                ),
            )
            if totals != (prompt_total, completion_total, prompt_total, completion_total):
                raise ComparisonError(f"{label}: client/server token totals differ")

            for metric in (
                "output_token_throughput_tps",
                "request_throughput_rps",
                "e2e_seconds_p95",
                "ttft_seconds_p95",
                "tpot_ms_p95",
            ):
                require_finite(row.get(metric), f"{label} {metric}", positive=True)
            for metric in (
                "peak_running_requests",
                "peak_waiting_requests",
                "peak_kv_cache_percent",
                "avg_pod_cpu_cores",
                "cpu_periods_delta",
                "cpu_throttled_periods_delta",
                "cpu_throttled_usec_delta",
                "cpu_throttled_time_percent",
                "peak_pod_memory_gib",
                "preemptions_delta",
            ):
                if require_finite(row.get(metric), f"{label} {metric}") < 0:
                    raise ComparisonError(f"{label}: {metric} is negative")
            if require_finite(
                row.get("peak_kv_cache_percent"), f"{label} peak KV"
            ) > 100 + 1e-6:
                raise ComparisonError(f"{label}: peak KV cache usage exceeds 100%")
            validate_speculative_counters(stage, row, label)

            memory_max = require_finite(
                row.get("memory_max_events_delta"), f"{label} memory.events:max"
            )
            if memory_max < 0:
                raise ComparisonError(f"{label}: memory.events:max is negative")
            if memory_max > 0:
                warnings.append(f"{label}: memory.events:max +{memory_max:g}")
            if require_finite(row.get("oom_events_delta"), f"{label} OOM") != 0 or require_finite(
                row.get("oom_kill_events_delta"), f"{label} OOM-kill"
            ) != 0:
                raise ComparisonError(f"{label}: OOM counters must be zero")
            phase_memory = phase.get("cgroup_memory_event_deltas")
            if not isinstance(phase_memory, dict) or set(phase_memory) != {
                "max",
                "oom",
                "oom_kill",
            }:
                raise ComparisonError(f"{label}: memory event deltas are malformed")
            phase_max = require_finite(
                phase_memory.get("max"), f"{label} phase memory.events:max"
            )
            if (
                phase_max != memory_max
                or require_finite(phase_memory.get("oom"), f"{label} phase OOM") != 0
                or require_finite(
                    phase_memory.get("oom_kill"), f"{label} phase OOM-kill"
                )
                != 0
            ):
                raise ComparisonError(f"{label}: phase/summary memory counters differ")
            expected_warnings = (
                [f"Pod cgroup memory max counter increased by {phase_max:g}"]
                if phase_max > 0
                else []
            )
            if phase.get("memory_pressure_warnings") != expected_warnings:
                raise ComparisonError(f"{label}: memory pressure warning differs")

            with metrics_path.open("r", encoding="utf-8", newline="") as handle:
                metric_rows = list(csv.DictReader(handle))
            if len(metric_rows) != int(phase["metrics_sample_count"]):
                raise ComparisonError(f"{label}: raw metric row count differs")
            tolerance = timedelta(seconds=1)
            for request in requests:
                request_start = parse_timestamp(
                    request.get("started_at_utc"), f"{label} request timestamp"
                )
                request_duration = require_finite(
                    request.get("e2e_seconds"), f"{label} request duration", positive=True
                )
                if request_start < phase_start - tolerance or (
                    request_start + timedelta(seconds=request_duration)
                    > phase_finish + tolerance
                ):
                    raise ComparisonError(f"{label}: request timer falls outside phase")

        if total_requests != len(CONCURRENCIES) * REQUESTS_PER_PHASE:
            raise ComparisonError(
                f"{stage.name}: expected exactly 700 requests, found {total_requests}"
            )

    assert canonical_requests is not None
    assert canonical_warmups is not None
    token_map = {str(item[1]): int(item[3]) for item in canonical_requests}
    if token_validation.get("counts_by_prompt_id") != token_map:
        raise ComparisonError("input token validation differs from raw prompt tokens")
    return {
        "canonical_requests": canonical_requests,
        "canonical_warmups": canonical_warmups,
        "pods": pods,
        "stage_times": stage_times,
        "warnings": warnings,
    }


def load_startup_evidence(
    results_root: Path,
    stages: tuple[StageSpec, ...],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> list[dict[str, Any]]:
    token_pattern = re.compile(r"GPU KV cache size: ([0-9,]+) tokens")
    concurrency_pattern = re.compile(
        r"Maximum concurrency for 2,048 tokens per request: ([0-9.]+)x"
    )
    output: list[dict[str, Any]] = []
    for stage in stages:
        directory = results_root / "startup-evidence" / stage.name
        log_path = directory / "startup.log"
        pod_path = directory / "pod.json"
        describe_path = directory / "describe.txt"
        for path in (log_path, pod_path, describe_path):
            if not path.is_file() or path.stat().st_size == 0:
                raise ComparisonError(f"{stage.name}: startup evidence is missing: {path}")
        log = log_path.read_text(encoding="utf-8")
        if "device_config=cpu" not in log:
            raise ComparisonError(f"{stage.name}: startup log does not prove CPU execution")
        budget = "0.75/8.0" if stage.kv_bytes == KV_768_BYTES else "0.5/8.0"
        if f"Explicitly set ({budget}) GiB for KV cache" not in log:
            raise ComparisonError(f"{stage.name}: startup KV budget marker is missing")
        dtype = "kv_cache_dtype=fp8" if stage.kv_dtype == "fp8" else "kv_cache_dtype=auto"
        if dtype not in log:
            raise ComparisonError(f"{stage.name}: startup dtype marker {dtype} is missing")
        if stage.mtp_enabled and "qwen3_next_mtp" not in log:
            raise ComparisonError(f"{stage.name}: startup log does not prove MTP2")
        token_matches = {int(value.replace(",", "")) for value in token_pattern.findall(log)}
        concurrency_matches = {float(value) for value in concurrency_pattern.findall(log)}
        if len(token_matches) != 1 or len(concurrency_matches) != 1:
            raise ComparisonError(f"{stage.name}: startup KV capacity is ambiguous")

        manifest_pod = loaded[stage.name][1]["environment"]["kubernetes"]["pods"][0]
        startup_pod = read_json(pod_path)
        statuses = startup_pod.get("status", {}).get("containerStatuses", [])
        if not isinstance(statuses, list) or len(statuses) != 1:
            raise ComparisonError(f"{stage.name}: startup Pod status is malformed")
        if (
            startup_pod.get("metadata", {}).get("uid") != manifest_pod.get("uid")
            or startup_pod.get("spec", {}).get("nodeName") != manifest_pod.get("node")
            or startup_pod.get("status", {}).get("phase") != "Running"
            or int(statuses[0].get("restartCount", -1)) != 0
            or statuses[0].get("imageID") != manifest_pod.get("image_id")
        ):
            raise ComparisonError(f"{stage.name}: startup Pod differs from formal run")
        if stage.kv_dtype == "fp8":
            for marker in (
                "Disabling calculate_kv_scales for hybrid model",
                "Using default scale of 1.0 instead",
            ):
                if marker not in log:
                    raise ComparisonError(f"{stage.name}: FP8 runtime marker is missing")

        output.append(
            {
                "stage_order": stage.order,
                "stage": stage.name,
                "display_name": stage.display_name,
                "cpu_limit": stage.cpu_limit,
                "mtp_enabled": str(stage.mtp_enabled).lower(),
                "kv_cache_mib": stage.kv_mib,
                "kv_cache_dtype": stage.kv_dtype,
                "kv_cache_tokens": next(iter(token_matches)),
                "max_concurrency_at_2048_tokens": fmt(
                    next(iter(concurrency_matches)), 2
                ),
                "pod_uid": manifest_pod["uid"],
                "restart_count": 0,
            }
        )
    return output


def gate_request_signature(
    rows: list[dict[str, Any]], label: str
) -> tuple[tuple[Any, ...], ...]:
    if len(rows) != 20:
        raise ComparisonError(f"{label}: expected 20 raw requests, found {len(rows)}")
    signature: list[tuple[Any, ...]] = []
    for sequence, request in enumerate(rows):
        if (
            int(request.get("sequence", -1)) != sequence
            or int(request.get("concurrency", -1)) != 20
            or request.get("status") != "success"
            or request.get("error") not in (None, "")
            or request.get("warmup") is not False
            or int(request.get("prompt_tokens", -1)) <= 0
            or int(request.get("completion_tokens", -1)) != 64
            or not request.get("prompt_id")
            or not request.get("source")
        ):
            raise ComparisonError(f"{label}: request {sequence} is invalid")
        signature.append(
            (
                sequence,
                request["prompt_id"],
                request["source"],
                int(request["prompt_tokens"]),
                int(request["completion_tokens"]),
            )
        )
    validate_response_fields(rows, label)
    return tuple(signature)


def validate_gate(
    results_root: Path,
    stage: StageSpec,
    preceding_stage: StageSpec,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    directory = results_root / "validation-gates" / f"{stage.name}-c20"
    summary_path = directory / "summary.json"
    manifest_path = directory / "run-manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise ComparisonError(f"{stage.name}: C20 compatibility gate is missing")
    summary = read_json(summary_path)
    manifest = read_json(manifest_path)
    recomputed_summary, recomputed_manifest = aggregate_raw(directory)
    if comparable(summary) != comparable(recomputed_summary) or manifest != recomputed_manifest:
        raise ComparisonError(f"{stage.name}: gate differs from raw aggregation")
    if not isinstance(summary, list) or len(summary) != 1 or not isinstance(manifest, dict):
        raise ComparisonError(f"{stage.name}: gate summary/manifest is malformed")
    row = summary[0]
    phases = manifest.get("phases")
    if (
        manifest.get("status") != "completed"
        or int(manifest.get("total_failures", -1)) != 0
        or manifest.get("concurrencies") != [20]
        or int(manifest.get("prompt_count", -1)) != 20
        or int(row.get("concurrency", -1)) != 20
        or (
            int(row.get("requests", -1)),
            int(row.get("successes", -1)),
            int(row.get("failures", -1)),
        )
        != (20, 20, 0)
        or not isinstance(phases, list)
        or len(phases) != 1
        or not isinstance(phases[0], dict)
    ):
        raise ComparisonError(f"{stage.name}: gate is not a completed 20/20 run")
    phase = phases[0]
    if (
        (
            int(phase.get("request_count", -1)),
            int(phase.get("success_count", -1)),
            int(phase.get("failure_count", -1)),
        )
        != (20, 20, 0)
        or int(phase.get("warmup_request_count", -1)) != WARMUP_REQUESTS
        or int(phase.get("metrics_sample_count", 0)) < 2
        or phase.get("metrics_scrape_errors") != []
        or phase.get("runtime_validation_errors") != []
    ):
        raise ComparisonError(f"{stage.name}: gate phase validation failed")

    formal_manifest = loaded[stage.name][1]
    if manifest.get("config") != formal_manifest.get("config"):
        raise ComparisonError(f"{stage.name}: gate/formal workload config differs")
    for key in ("prompts_sha256", "prompts_file", "runner_sha256", "server_version"):
        if manifest.get(key) != formal_manifest.get(key):
            raise ComparisonError(f"{stage.name}: gate/formal {key} differs")
    if model_signature(manifest.get("model_endpoint")) != model_signature(
        formal_manifest.get("model_endpoint")
    ):
        raise ComparisonError(f"{stage.name}: gate/formal model differs")
    formal_environment = formal_manifest.get("environment", {})
    gate_environment = manifest.get("environment", {})
    for key in ("host", "docker", "git"):
        if gate_environment.get(key) != formal_environment.get(key):
            raise ComparisonError(f"{stage.name}: gate/formal {key} environment differs")
    if gate_environment.get("kubernetes", {}).get("nodes") != formal_environment.get(
        "kubernetes", {}
    ).get("nodes"):
        raise ComparisonError(f"{stage.name}: gate/formal node inventory differs")
    gate_pod = validate_container(stage, manifest)
    formal_pod = validation["pods"][stage.name]
    for field in ("uid", "node", "image_id"):
        if gate_pod.get(field) != formal_pod.get(field):
            raise ComparisonError(f"{stage.name}: gate/formal Pod {field} differs")

    raw_phase_path = directory / "raw" / "phase-c20.json"
    if not raw_phase_path.is_file() or read_json(raw_phase_path) != phase:
        raise ComparisonError(f"{stage.name}: gate raw phase differs or is missing")
    requests_path = resolve_phase_artifact(
        directory, phase.get("requests_file"), f"{stage.name} gate requests"
    )
    metrics_path = resolve_phase_artifact(
        directory, phase.get("metrics_file"), f"{stage.name} gate metrics"
    )
    requests = read_jsonl(requests_path)
    signature = gate_request_signature(requests, f"{stage.name} gate C=20")
    if signature != validation["canonical_requests"][:20]:
        raise ComparisonError(f"{stage.name}: gate is not the first 20 formal prompts")
    warmups = warmup_signature(
        phase.get("warmup_results"), 20, f"{stage.name} gate C=20"
    )
    if warmups != validation["canonical_warmups"]:
        raise ComparisonError(f"{stage.name}: gate warmup workload differs")
    token_map = {str(item[1]): int(item[3]) for item in signature}
    token_validation = manifest.get("input_token_validation")
    if not isinstance(token_validation, dict) or token_validation.get(
        "counts_by_prompt_id"
    ) != token_map:
        raise ComparisonError(f"{stage.name}: gate token validation differs")
    prompt_total = sum(int(item[3]) for item in signature)
    completion_total = sum(int(item[4]) for item in signature)
    totals = (
        int(require_finite(row.get("total_prompt_tokens"), "gate prompt")),
        int(require_finite(row.get("total_completion_tokens"), "gate completion")),
        int(require_finite(row.get("server_prompt_tokens_delta"), "gate server prompt")),
        int(
            require_finite(
                row.get("server_generation_tokens_delta"), "gate server completion"
            )
        ),
    )
    if totals != (prompt_total, completion_total, prompt_total, completion_total):
        raise ComparisonError(f"{stage.name}: gate client/server tokens differ")
    for metric in (
        "output_token_throughput_tps",
        "request_throughput_rps",
        "e2e_seconds_p95",
        "ttft_seconds_p95",
        "tpot_ms_p95",
    ):
        require_finite(row.get(metric), f"{stage.name} gate {metric}", positive=True)
    validate_speculative_counters(stage, row, f"{stage.name} gate")
    memory_max = require_finite(
        row.get("memory_max_events_delta"), f"{stage.name} gate memory.max"
    )
    if memory_max < 0:
        raise ComparisonError(f"{stage.name}: gate memory.max is negative")
    if require_finite(row.get("oom_events_delta"), f"{stage.name} gate OOM") != 0 or require_finite(
        row.get("oom_kill_events_delta"), f"{stage.name} gate OOM-kill"
    ) != 0:
        raise ComparisonError(f"{stage.name}: gate OOM counters must be zero")
    phase_memory = phase.get("cgroup_memory_event_deltas")
    if not isinstance(phase_memory, dict) or (
        require_finite(phase_memory.get("max"), f"{stage.name} gate phase max")
        != memory_max
        or require_finite(phase_memory.get("oom"), f"{stage.name} gate phase OOM")
        != 0
        or require_finite(
            phase_memory.get("oom_kill"), f"{stage.name} gate phase OOM-kill"
        )
        != 0
    ):
        raise ComparisonError(f"{stage.name}: gate memory counters differ")
    with metrics_path.open("r", encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    if len(metric_rows) != int(phase["metrics_sample_count"]):
        raise ComparisonError(f"{stage.name}: gate raw metric count differs")

    gate_start = parse_timestamp(manifest.get("started_at_utc"), f"{stage.name} gate start")
    gate_finish = parse_timestamp(
        manifest.get("finished_at_utc"), f"{stage.name} gate finish"
    )
    phase_start = parse_timestamp(
        phase.get("started_at_utc"), f"{stage.name} gate phase start"
    )
    phase_finish = parse_timestamp(
        phase.get("finished_at_utc"), f"{stage.name} gate phase finish"
    )
    duration = require_finite(
        phase.get("duration_seconds"), f"{stage.name} gate duration", positive=True
    )
    if (
        gate_finish <= gate_start
        or phase_start < gate_start
        or phase_finish > gate_finish
        or abs((phase_finish - phase_start).total_seconds() - duration)
        > max(5.0, duration * 0.01)
    ):
        raise ComparisonError(f"{stage.name}: gate timestamp validation failed")
    if gate_start < validation["stage_times"][preceding_stage.name][1] or gate_finish > validation[
        "stage_times"
    ][stage.name][0]:
        raise ComparisonError(
            f"{stage.name}: gate must be between preceding and formal stage"
        )
    return {
        "stage": stage.name,
        "concurrency": 20,
        "requests": 20,
        "successes": 20,
        "failures": 0,
        "output_tps": fmt(row.get("output_token_throughput_tps")),
        "e2e_p95_seconds": fmt(row.get("e2e_seconds_p95")),
        "ttft_p95_seconds": fmt(row.get("ttft_seconds_p95")),
        "tpot_p95_ms": fmt(row.get("tpot_ms_p95")),
        "peak_running": fmt(row.get("peak_running_requests"), 0),
        "peak_waiting": fmt(row.get("peak_waiting_requests"), 0),
        "peak_memory_gib": fmt(row.get("peak_pod_memory_gib")),
        "memory_max_events": fmt(memory_max, 0),
        "oom_events": 0,
        "oom_kill_events": 0,
    }


def validate_gates(
    results_root: Path,
    stages: tuple[StageSpec, ...],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
    validation: dict[str, Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, stage in enumerate(stages):
        if stage.kv_dtype != "fp8":
            continue
        if index == 0:
            raise ComparisonError("an FP8 stage cannot be first in the formal sequence")
        output.append(
            validate_gate(
                results_root,
                stage,
                stages[index - 1],
                loaded,
                validation,
            )
        )
    return output


def build_rows(
    results_root: Path,
    stages: tuple[StageSpec, ...],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_stage = {
        name: {int(row["concurrency"]): row for row in rows}
        for name, (rows, _manifest) in loaded.items()
    }
    output: list[dict[str, Any]] = []
    for stage in stages:
        for concurrency in CONCURRENCIES:
            current = by_stage[stage.name][concurrency]
            baseline = by_stage[BASELINE.name][concurrency]
            filename = f"requests-c{concurrency:02d}.jsonl"
            baseline_requests = read_jsonl(
                results_root / BASELINE.name / "raw" / filename
            )
            current_requests = read_jsonl(results_root / stage.name / "raw" / filename)
            if len(baseline_requests) != 100 or len(current_requests) != 100:
                raise ComparisonError(
                    f"{stage.name} C={concurrency}: hash comparison is not 100 vs 100"
                )
            hash_matches = 0
            for index, (before, after) in enumerate(
                zip(baseline_requests, current_requests, strict=True)
            ):
                identity_before = (
                    before.get("sequence"),
                    before.get("prompt_id"),
                    before.get("source"),
                )
                identity_after = (
                    after.get("sequence"),
                    after.get("prompt_id"),
                    after.get("source"),
                )
                if identity_before != identity_after:
                    raise ComparisonError(
                        f"{stage.name} C={concurrency}: response identity differs at {index}"
                    )
                if before.get("content_sha256") == after.get("content_sha256"):
                    hash_matches += 1

            def effect(metric: str) -> str:
                return "" if stage is BASELINE else fmt(
                    percent_change(baseline[metric], current[metric])
                )

            output.append(
                {
                    "stage_order": stage.order,
                    "stage": stage.name,
                    "display_name": stage.display_name,
                    "factor_vs_baseline": stage.changed_factor,
                    "concurrency": concurrency,
                    "cpu_limit": stage.cpu_limit,
                    "mtp_enabled": str(stage.mtp_enabled).lower(),
                    "kv_cache_mib": stage.kv_mib,
                    "kv_cache_dtype": stage.kv_dtype,
                    "requests": int(current["requests"]),
                    "output_tps": fmt(current["output_token_throughput_tps"]),
                    "baseline_output_tps": fmt(baseline["output_token_throughput_tps"]),
                    "output_vs_baseline_percent": effect(
                        "output_token_throughput_tps"
                    ),
                    "request_rps": fmt(current["request_throughput_rps"]),
                    "request_rps_vs_baseline_percent": effect("request_throughput_rps"),
                    "e2e_p95_seconds": fmt(current["e2e_seconds_p95"]),
                    "e2e_p95_vs_baseline_percent": effect("e2e_seconds_p95"),
                    "ttft_p95_seconds": fmt(current["ttft_seconds_p95"]),
                    "ttft_p95_vs_baseline_percent": effect("ttft_seconds_p95"),
                    "tpot_p95_ms": fmt(current["tpot_ms_p95"]),
                    "tpot_p95_vs_baseline_percent": effect("tpot_ms_p95"),
                    "peak_running": fmt(current["peak_running_requests"], 0),
                    "peak_waiting": fmt(current["peak_waiting_requests"], 0),
                    "peak_kv_percent": fmt(current["peak_kv_cache_percent"]),
                    "avg_cpu_cores": fmt(current["avg_pod_cpu_cores"]),
                    "cpu_throttled_time_percent": fmt(
                        current["cpu_throttled_time_percent"]
                    ),
                    "peak_memory_gib": fmt(current["peak_pod_memory_gib"]),
                    "preemptions": fmt(current["preemptions_delta"], 0),
                    "spec_drafts": (
                        fmt(current.get("spec_drafts_delta"), 0)
                        if stage.mtp_enabled
                        else "0"
                    ),
                    "spec_draft_tokens": (
                        fmt(current.get("spec_draft_tokens_delta"), 0)
                        if stage.mtp_enabled
                        else "0"
                    ),
                    "spec_accepted_tokens": (
                        fmt(current.get("spec_accepted_tokens_delta"), 0)
                        if stage.mtp_enabled
                        else "0"
                    ),
                    "spec_acceptance_percent": (
                        fmt(current.get("spec_acceptance_percent"))
                        if stage.mtp_enabled
                        else "0"
                    ),
                    "memory_max_events": fmt(current["memory_max_events_delta"], 0),
                    "oom_events": fmt(current["oom_events_delta"], 0),
                    "oom_kill_events": fmt(current["oom_kill_events_delta"], 0),
                    "exact_response_hash_matches": hash_matches,
                    "exact_response_hash_match_percent": fmt(hash_matches),
                }
            )
    return output


def svg_header(width: int, height: int, title: str, description: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(title)}</title>',
        f'<desc id="desc">{html.escape(description)}</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]


def write_absolute_line_svg(
    path: Path,
    title: str,
    subtitle: str,
    y_label: str,
    metric: str,
    stages: tuple[StageSpec, ...],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> None:
    width, height = 1180, 650
    left, right, top, bottom = 90, 40, 155, 70
    plot_width = width - left - right
    plot_height = height - top - bottom
    series: list[tuple[StageSpec, list[float]]] = []
    for stage in stages:
        values = [finite(row[metric]) for row in loaded[stage.name][0]]
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ComparisonError(f"{stage.name}: {metric} is not chartable")
        series.append((stage, values))
    y_max = nice_max(max(value for _stage, values in series for value in values) * 1.08)

    def x_position(index: int) -> float:
        return left + index / (len(CONCURRENCIES) - 1) * plot_width

    def y_position(value: float) -> float:
        return top + (y_max - value) / y_max * plot_height

    parts = svg_header(
        width,
        height,
        title,
        f"{title} at client concurrencies 1, 2, 5, 10, 20, 50 and 100.",
    )
    parts.extend(
        (
            f'<text x="{width / 2}" y="34" text-anchor="middle" font-size="22" '
            f'font-family="sans-serif" font-weight="600">{html.escape(title)}</text>',
            f'<text x="{width / 2}" y="59" text-anchor="middle" font-size="13" '
            f'font-family="sans-serif" fill="#4b5563">{html.escape(subtitle)}</text>',
        )
    )
    for index, stage in enumerate(stages):
        legend_x = left + (index % 3) * 350
        legend_y = 89 + (index // 3) * 27
        color = COLORS[stage.name]
        parts.extend(
            (
                f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" '
                f'y2="{legend_y}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{legend_x + 31}" y="{legend_y + 4}" font-size="12" '
                f'font-family="sans-serif">{html.escape(stage.display_name)}</text>',
            )
        )
    for tick in range(6):
        value = y_max * tick / 5
        y = y_position(value)
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" '
                f'y2="{y:.2f}" stroke="#e5e7eb"/>',
                f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" '
                f'font-size="12" font-family="sans-serif" fill="#4b5563">{value:.1f}</text>',
            )
        )
    for index, concurrency in enumerate(CONCURRENCIES):
        x = x_position(index)
        parts.extend(
            (
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" '
                f'y2="{top + plot_height}" stroke="#f3f4f6"/>',
                f'<text x="{x:.2f}" y="{top + plot_height + 25}" text-anchor="middle" '
                f'font-size="13" font-family="sans-serif">{concurrency}</text>',
            )
        )
    parts.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" '
            f'y2="{top + plot_height}" stroke="#111827"/>',
            f'<text x="{left + plot_width / 2}" y="{height - 18}" text-anchor="middle" '
            'font-size="14" font-family="sans-serif">Client concurrency</text>',
            f'<text transform="translate(23 {top + plot_height / 2}) rotate(-90)" '
            f'text-anchor="middle" font-size="14" font-family="sans-serif">{html.escape(y_label)}</text>',
        )
    )
    for stage, values in series:
        color = COLORS[stage.name]
        points = " ".join(
            f"{x_position(index):.2f},{y_position(value):.2f}"
            for index, value in enumerate(values)
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.8"/>'
        )
        for index, value in enumerate(values):
            parts.append(
                f'<circle cx="{x_position(index):.2f}" cy="{y_position(value):.2f}" '
                f'r="4" fill="{color}"/>'
            )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_factor_effects_svg(
    path: Path,
    stages: tuple[StageSpec, ...],
    rows: list[dict[str, Any]],
) -> None:
    treatments = tuple(stage for stage in stages if stage is not BASELINE)
    row_by_key = {(row["stage"], int(row["concurrency"])): row for row in rows}
    series: list[tuple[StageSpec, list[float]]] = []
    for stage in treatments:
        values = [
            require_finite(
                row_by_key[(stage.name, concurrency)]["output_vs_baseline_percent"],
                f"{stage.name} C={concurrency} factor effect",
            )
            for concurrency in CONCURRENCIES
        ]
        series.append((stage, values))
    bound = nice_max(
        max(abs(value) for _stage, values in series for value in values) * 1.12
    )
    width, height = 1180, 630
    left, right, top, bottom = 90, 40, 145, 70
    plot_width = width - left - right
    plot_height = height - top - bottom

    def x_position(index: int) -> float:
        return left + index / (len(CONCURRENCIES) - 1) * plot_width

    def y_position(value: float) -> float:
        return top + (bound - value) / (2 * bound) * plot_height

    parts = svg_header(
        width,
        height,
        "Independent CPU8 factor effects versus baseline",
        "Output-throughput percentage change for each independently controlled factor "
        "relative to the same CPU8 baseline.",
    )
    parts.extend(
        (
            f'<text x="{width / 2}" y="34" text-anchor="middle" font-size="22" '
            'font-family="sans-serif" font-weight="600">Independent factor effects vs CPU8 baseline</text>',
            f'<text x="{width / 2}" y="59" text-anchor="middle" font-size="13" '
            'font-family="sans-serif" fill="#4b5563">Output throughput change · positive is faster</text>',
        )
    )
    for index, stage in enumerate(treatments):
        legend_x = left + (index % 3) * 350
        legend_y = 88 + (index // 3) * 27
        color = COLORS[stage.name]
        parts.extend(
            (
                f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" '
                f'y2="{legend_y}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{legend_x + 31}" y="{legend_y + 4}" font-size="12" '
                f'font-family="sans-serif">{html.escape(stage.display_name)}</text>',
            )
        )
    for tick in range(5):
        value = -bound + 2 * bound * tick / 4
        y = y_position(value)
        stroke = "#6b7280" if abs(value) < 1e-9 else "#e5e7eb"
        width_value = "1.8" if abs(value) < 1e-9 else "1"
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" '
                f'y2="{y:.2f}" stroke="{stroke}" stroke-width="{width_value}"/>',
                f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" '
                f'font-size="12" font-family="sans-serif" fill="#4b5563">{value:+.0f}%</text>',
            )
        )
    for index, concurrency in enumerate(CONCURRENCIES):
        x = x_position(index)
        parts.extend(
            (
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" '
                f'y2="{top + plot_height}" stroke="#f3f4f6"/>',
                f'<text x="{x:.2f}" y="{top + plot_height + 25}" text-anchor="middle" '
                f'font-size="13" font-family="sans-serif">{concurrency}</text>',
            )
        )
    for stage, values in series:
        color = COLORS[stage.name]
        points = " ".join(
            f"{x_position(index):.2f},{y_position(value):.2f}"
            for index, value in enumerate(values)
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.8"/>'
        )
        for index, value in enumerate(values):
            parts.append(
                f'<circle cx="{x_position(index):.2f}" cy="{y_position(value):.2f}" '
                f'r="4" fill="{color}"/>'
            )
    parts.extend(
        (
            f'<text x="{left + plot_width / 2}" y="{height - 18}" text-anchor="middle" '
            'font-size="14" font-family="sans-serif">Client concurrency</text>',
            f'<text transform="translate(23 {top + plot_height / 2}) rotate(-90)" '
            'text-anchor="middle" font-size="14" font-family="sans-serif">Output throughput change vs baseline</text>',
            "</svg>",
        )
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_scheduler_pressure_svg(
    path: Path,
    stages: tuple[StageSpec, ...],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> None:
    width, height = 1180, 820
    left, right = 90, 40
    plot_width = width - left - right
    panel_height = 230
    panel_tops = (165, 500)
    metrics = (
        ("peak_running_requests", "Peak running requests"),
        ("peak_waiting_requests", "Peak waiting requests"),
    )
    data: dict[str, dict[str, list[float]]] = {}
    for metric, _label in metrics:
        data[metric] = {}
        for stage in stages:
            values = [finite(row[metric]) for row in loaded[stage.name][0]]
            if any(not math.isfinite(value) or value < 0 for value in values):
                raise ComparisonError(f"{stage.name}: {metric} is not chartable")
            data[metric][stage.name] = values

    def x_position(index: int) -> float:
        return left + index / (len(CONCURRENCIES) - 1) * plot_width

    parts = svg_header(
        width,
        height,
        "Windows CPU8 factor scheduler pressure",
        "Separate panels compare sampled peak running and waiting requests for each factor.",
    )
    parts.extend(
        (
            f'<text x="{width / 2}" y="34" text-anchor="middle" font-size="22" '
            'font-family="sans-serif" font-weight="600">CPU8 factor scheduler pressure</text>',
            f'<text x="{width / 2}" y="59" text-anchor="middle" font-size="13" '
            'font-family="sans-serif" fill="#4b5563">sampled phase peaks · running and waiting use separate panels</text>',
        )
    )
    for index, stage in enumerate(stages):
        legend_x = left + (index % 3) * 350
        legend_y = 91 + (index // 3) * 27
        color = COLORS[stage.name]
        parts.extend(
            (
                f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" '
                f'y2="{legend_y}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{legend_x + 31}" y="{legend_y + 4}" font-size="12" '
                f'font-family="sans-serif">{html.escape(stage.display_name)}</text>',
            )
        )

    for panel_index, (metric, label) in enumerate(metrics):
        top = panel_tops[panel_index]
        values = [value for stage_values in data[metric].values() for value in stage_values]
        y_max = nice_max(max(values) * 1.08 if values else 1.0)

        def y_position(value: float, *, _top: int = top, _max: float = y_max) -> float:
            return _top + (_max - value) / _max * panel_height

        parts.append(
            f'<text x="{left}" y="{top - 18}" font-size="16" '
            f'font-family="sans-serif" font-weight="600">{label}</text>'
        )
        for tick in range(5):
            value = y_max * tick / 4
            y = y_position(value)
            parts.extend(
                (
                    f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" '
                    f'y2="{y:.2f}" stroke="#e5e7eb"/>',
                    f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" '
                    f'font-size="12" font-family="sans-serif" fill="#4b5563">{value:.0f}</text>',
                )
            )
        for index, concurrency in enumerate(CONCURRENCIES):
            x = x_position(index)
            parts.append(
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" '
                f'y2="{top + panel_height}" stroke="#f3f4f6"/>'
            )
            if panel_index == 1:
                parts.append(
                    f'<text x="{x:.2f}" y="{top + panel_height + 25}" '
                    f'text-anchor="middle" font-size="13" font-family="sans-serif">{concurrency}</text>'
                )
        for stage in stages:
            color = COLORS[stage.name]
            values_for_stage = data[metric][stage.name]
            points = " ".join(
                f"{x_position(index):.2f},{y_position(value):.2f}"
                for index, value in enumerate(values_for_stage)
            )
            parts.append(
                f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.8"/>'
            )
            for index, value in enumerate(values_for_stage):
                parts.append(
                    f'<circle cx="{x_position(index):.2f}" cy="{y_position(value):.2f}" '
                    f'r="4" fill="{color}"/>'
                )
    parts.extend(
        (
            f'<text x="{left + plot_width / 2}" y="{height - 18}" text-anchor="middle" '
            'font-size="14" font-family="sans-serif">Client concurrency</text>',
            "</svg>",
        )
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def write_report(
    output: Path,
    stages: tuple[StageSpec, ...],
    rows: list[dict[str, Any]],
    startup_rows: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    warnings: list[str],
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
    suite_manifest: dict[str, Any],
) -> None:
    row_by_key = {(row["stage"], int(row["concurrency"])): row for row in rows}
    matrix = [
        "| 구성 | CPU | MTP2 | KV budget | KV cache | baseline 대비 변수 |",
        "|---|---:|---|---:|---|---|",
    ]
    for stage in stages:
        matrix.append(
            f"| `{stage.name}` | 8 | {'on' if stage.mtp_enabled else 'off'} | "
            f"{stage.kv_mib}MiB | {'FP8 KV' if stage.kv_dtype == 'fp8' else 'BF16'} | "
            f"{stage.changed_factor} |"
        )

    throughput = [
        "| C | " + " | ".join(stage.display_name for stage in stages) + " |",
        "|---:|" + "---:|" * len(stages),
    ]
    for concurrency in CONCURRENCIES:
        values = [
            f"{float(row_by_key[(stage.name, concurrency)]['output_tps']):.2f}"
            for stage in stages
        ]
        throughput.append(f"| {concurrency} | " + " | ".join(values) + " |")

    effects = [
        "| C | "
        + " | ".join(f"{stage.display_name} vs baseline" for stage in stages[1:])
        + " |",
        "|---:|" + "---:|" * (len(stages) - 1),
    ]
    for concurrency in CONCURRENCIES:
        values = [
            f"{float(row_by_key[(stage.name, concurrency)]['output_vs_baseline_percent']):+.1f}%"
            for stage in stages[1:]
        ]
        effects.append(f"| {concurrency} | " + " | ".join(values) + " |")

    pressure = [
        "| C | " + " | ".join(stage.display_name for stage in stages) + " |",
        "|---:|" + "---:|" * len(stages),
    ]
    for concurrency in CONCURRENCIES:
        values = [
            f"{int(float(row_by_key[(stage.name, concurrency)]['peak_running']))}/"
            f"{int(float(row_by_key[(stage.name, concurrency)]['peak_waiting']))}"
            for stage in stages
        ]
        pressure.append(f"| {concurrency} | " + " | ".join(values) + " |")

    startup_by_stage = {row["stage"]: row for row in startup_rows}
    startup = [
        "| 구성 | KV token capacity | max concurrency @ 2,048 tokens |",
        "|---|---:|---:|",
    ]
    for stage in stages:
        item = startup_by_stage[stage.name]
        startup.append(
            f"| {stage.display_name} | {int(item['kv_cache_tokens']):,} | "
            f"{float(item['max_concurrency_at_2048_tokens']):.2f}x |"
        )

    stability = [
        "| 구성 | 최대 memory | 최대 avg CPU | 최대 throttled time | preemption 합계 | memory.max 합계 | OOM/OOM-kill |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    by_stage = {
        name: {int(row["concurrency"]): row for row in stage_rows}
        for name, (stage_rows, _manifest) in loaded.items()
    }
    for stage in stages:
        stage_values = [by_stage[stage.name][c] for c in CONCURRENCIES]
        stability.append(
            f"| {stage.display_name} | "
            f"{max(finite(row['peak_pod_memory_gib']) for row in stage_values):.3f}GiB | "
            f"{max(finite(row['avg_pod_cpu_cores']) for row in stage_values):.2f} cores | "
            f"{max(finite(row['cpu_throttled_time_percent']) for row in stage_values):.2f}% | "
            f"{sum(int(finite(row['preemptions_delta'])) for row in stage_values)} | "
            f"{sum(int(finite(row['memory_max_events_delta'])) for row in stage_values)} | "
            f"{sum(int(finite(row['oom_events_delta'])) for row in stage_values)}/"
            f"{sum(int(finite(row['oom_kill_events_delta'])) for row in stage_values)} |"
        )

    mtp_acceptance = [
        "| C | MTP acceptance |",
        "|---:|---:|",
    ]
    for concurrency in CONCURRENCIES:
        mtp_acceptance.append(
            f"| {concurrency} | "
            f"{float(row_by_key[(MTP_ONLY.name, concurrency)]['spec_acceptance_percent']):.1f}% |"
        )

    gate_text = "\n".join(
        f"- `{gate['stage']}`: C20 `{int(gate['successes'])}/{int(gate['requests'])}` 성공, "
        f"output `{float(gate['output_tps']):.2f}` tok/s, E2E p95 "
        f"`{float(gate['e2e_p95_seconds']):.3f}s`"
        for gate in gates
    )
    warning_text = (
        "\n".join(f"- {warning}" for warning in warnings)
        if warnings
        else "- 모든 formal phase에서 `memory.events:max` delta는 0이었다."
    )
    request_total = len(stages) * len(CONCURRENCIES) * REQUESTS_PER_PHASE

    discussion: list[str] = []
    for stage in stages[1:]:
        deltas = {
            c: float(row_by_key[(stage.name, c)]["output_vs_baseline_percent"])
            for c in CONCURRENCIES
        }
        wins = sum(value > 0 for value in deltas.values())
        low = mean([deltas[c] for c in (1, 2, 5)])
        high = mean([deltas[c] for c in (10, 20, 50, 100)])
        best = max(deltas, key=deltas.get)
        worst = min(deltas, key=deltas.get)
        discussion.append(
            f"- **{stage.display_name}:** 7개 지점 중 {wins}개에서 baseline보다 높았다. "
            f"C1~C5 평균은 {low:+.1f}%, C10~C100 평균은 {high:+.1f}%이며, "
            f"범위는 C{worst} {deltas[worst]:+.1f}% ~ C{best} {deltas[best]:+.1f}%다."
        )
    if COMBO in stages:
        interaction_values: list[float] = []
        for concurrency in CONCURRENCIES:
            kv = float(
                row_by_key[(KV768_ONLY.name, concurrency)][
                    "output_vs_baseline_percent"
                ]
            ) / 100
            fp8 = float(
                row_by_key[(FP8_ONLY.name, concurrency)][
                    "output_vs_baseline_percent"
                ]
            ) / 100
            combo = float(
                row_by_key[(COMBO.name, concurrency)]["output_vs_baseline_percent"]
            ) / 100
            independent_expectation = (1 + kv) * (1 + fp8) - 1
            interaction_values.append(100 * (combo - independent_expectation))
        discussion.append(
            f"- **결합 효과:** KV768과 FP8 KV의 독립 효과를 곱해 예측한 값 대비 "
            f"결합 구성의 평균 interaction은 {mean(interaction_values):+.1f}%p다."
        )

    report = f"""# Windows CPU8 독립 요인 실험

## 실험 목적

동일한 CPU8 baseline에서 MTP2, KV budget 768MiB, FP8 KV를 각각 하나씩만 적용해 독립 효과를 측정했다. 두 독립 요인이 모두 이득일 때 사용할 수 있는 KV768+FP8 KV 결합 구성은 결과가 존재하는 경우에만 추가 분석한다.

## 검증 결과

- {len(stages)}개 구성 × 7개 concurrency × 100건 = `{request_total:,}/{request_total:,}` formal 요청 성공을 검증했다.
- core 4개 구성의 `2,800/2,800`은 필수이며, 결합 구성은 `{'포함되어 총 3,500건을 검증했다' if COMBO in stages else '이번 실행에 포함되지 않았다'}`.
- `summary.json`은 raw request, server/cgroup metric, phase artifact에서 다시 집계해 저장본과 일치함을 확인했다.
- host, Docker, Kubernetes node, immutable image, runner, Git 상태, 모델, workload, 입력 token 순서를 모든 구성에서 동일하게 대조했다.
- `suite-manifest.json`의 source fingerprint, runner hash, Docker fingerprint, Git commit과 invocation 이력을 formal manifest에 대조했다. 비교 시 suite 상태는 `{suite_manifest['status']}`였다.
- 모든 formal phase의 restart, metric scrape error, runtime validation error, OOM, OOM-kill은 0이다.
- MTP draft/acceptance activity는 MTP-only 구성에서만 증가했고, 나머지 구성의 delta는 0으로 정규화해 확인했다.

## 실험 구성

{chr(10).join(matrix)}

## Output throughput

단위는 output tokens/second이다.

{chr(10).join(throughput)}

![Output throughput](output-throughput.svg)

## 독립 요인 효과

각 값은 같은 concurrency의 공통 CPU8 baseline 대비 output throughput 변화율이다.

{chr(10).join(effects)}

![Factor effects](factor-effects.svg)

{chr(10).join(discussion)}

## Scheduler pressure

표의 값은 `peak running / peak waiting`이다.

{chr(10).join(pressure)}

![Scheduler pressure](scheduler-pressure.svg)

## MTP acceptance

{chr(10).join(mtp_acceptance)}

## 기동 KV capacity

{chr(10).join(startup)}

## 자원과 안정성

{chr(10).join(stability)}

{warning_text}

## FP8 compatibility gate

{gate_text}

게이트 요청은 formal 요청 수에 포함하지 않았다.

## 타당성 위협과 후속 실험

이번 결과는 같은 Windows 호스트에서 정해진 순서로 한 번씩 실행한 controlled screen이다. 실행 순서, 온도와 백그라운드 부하의 영향을 분리하려면 요인별 반복 측정과 순서 교차가 필요하다. 결합 효과는 단일 2-factor 조합만 확인하므로 전체 interaction을 설명하지 않는다. 후속 실험은 유효한 독립 요인만 대상으로 반복 횟수를 늘리고, 동시성 구간별 admission limit 및 replica scaling을 함께 평가해야 한다.

전체 phase 수치와 baseline 대비 효과는 [comparison.csv](comparison.csv), 기동 capacity는 [startup-capacity.csv](startup-capacity.csv)에 저장했다.
"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-root",
        type=Path,
        default=repository / "benchmark" / "results-windows-cpu8-factors-20260830",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="default: <results-root>/comparison-cpu8-factors",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_root = args.results_root.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else results_root / "comparison-cpu8-factors"
    )
    try:
        stages = active_stages(results_root)
        loaded = load_results(results_root, stages)
        suite_manifest = validate_suite_manifest(results_root, loaded)
        validation = validate_results(results_root, stages, loaded)
        startup_rows = load_startup_evidence(results_root, stages, loaded)
        gates = validate_gates(results_root, stages, loaded, validation)
        rows = build_rows(results_root, stages, loaded)
        output.mkdir(parents=True, exist_ok=True)
        write_csv(output / "comparison.csv", rows)
        write_csv(output / "startup-capacity.csv", startup_rows)
        write_absolute_line_svg(
            output / "output-throughput.svg",
            "Windows CPU8 independent-factor output throughput",
            "same workload, image, host and CPU limit · 100 requests per point",
            "Output tokens / second",
            "output_token_throughput_tps",
            stages,
            loaded,
        )
        write_factor_effects_svg(output / "factor-effects.svg", stages, rows)
        write_scheduler_pressure_svg(
            output / "scheduler-pressure.svg", stages, loaded
        )
        write_report(
            output,
            stages,
            rows,
            startup_rows,
            gates,
            validation["warnings"],
            loaded,
            suite_manifest,
        )
    except (
        ComparisonError,
        FileNotFoundError,
        json.JSONDecodeError,
        csv.Error,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    formal_requests = len(stages) * len(CONCURRENCIES) * REQUESTS_PER_PHASE
    print(
        f"Validated {len(stages)} stages, {len(rows)} phase rows, "
        f"{formal_requests} formal requests, {len(gates)} gate(s), and wrote {output}"
    )
    if validation["warnings"]:
        print(f"memory.events:max warnings: {len(validation['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
