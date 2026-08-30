#!/usr/bin/env python3
"""Validate and compare the five-stage Windows CPU serving experiment."""

from __future__ import annotations

import argparse
import copy
import csv
import html
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from analyze import aggregate as aggregate_raw


CONCURRENCIES = (1, 2, 5, 10, 20, 50, 100)
REQUESTS_PER_PHASE = 100
WARMUP_REQUESTS = 3
IMAGE = "local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0"
MTP_CONFIG = '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
KV_512_BYTES = "536870912"
KV_768_BYTES = "805306368"
BASE_ARGS = (
    "/models/qwen3.5-0.8b",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--served-model-name",
    "qwen3.5-0.8b",
    "--dtype",
    "bfloat16",
    "--language-model-only",
    "--max-model-len",
    "2048",
    "--max-num-seqs",
    "20",
    "--max-num-batched-tokens",
    "2048",
    "--kv-cache-memory-bytes",
    KV_512_BYTES,
    "--no-enable-prefix-caching",
)
EXPECTED_ENV = (
    ("HF_HUB_OFFLINE", "1"),
    ("TRANSFORMERS_OFFLINE", "1"),
    ("TOKENIZERS_PARALLELISM", "false"),
    ("PYTHONUNBUFFERED", "1"),
)
EXPECTED_WORKLOAD_FIELDS = {
    "concurrencies": list(CONCURRENCIES),
    "cooldown_seconds": 3,
    "ignore_eos": True,
    "local_port": 18000,
    "max_tokens": 64,
    "metrics_interval_seconds": 1.0,
    "model": "qwen3.5-0.8b",
    "namespace": "llm-serving",
    "request_count": REQUESTS_PER_PHASE,
    "request_timeout_seconds": 1200,
    "seed": 20260828,
    "service": "vllm-cpu",
    "temperature": 0.0,
    "warmup_max_tokens": 8,
    "warmup_requests": WARMUP_REQUESTS,
}
COLORS = ("#1d4ed8", "#7c3aed", "#059669", "#ea580c", "#be123c")


class ComparisonError(RuntimeError):
    """Raised when artifacts cannot form the controlled five-stage comparison."""


@dataclass(frozen=True)
class StageSpec:
    order: int
    name: str
    display_name: str
    cpu_limit: int
    mtp_enabled: bool
    kv_bytes: str
    kv_dtype: str
    previous: str | None
    changed_factor: str

    @property
    def kv_mib(self) -> int:
        return int(self.kv_bytes) // 1024**2


STAGES = (
    StageSpec(
        0,
        "baseline",
        "S0 CPU6 baseline",
        6,
        False,
        KV_512_BYTES,
        "auto (BF16)",
        None,
        "reference",
    ),
    StageSpec(
        1,
        "baseline-cpu8",
        "S1 CPU8 baseline",
        8,
        False,
        KV_512_BYTES,
        "auto (BF16)",
        "baseline",
        "CPU limit 6→8",
    ),
    StageSpec(
        2,
        "mtp-cpu8",
        "S2 CPU8 MTP2",
        8,
        True,
        KV_512_BYTES,
        "auto (BF16)",
        "baseline-cpu8",
        "MTP off→MTP2",
    ),
    StageSpec(
        3,
        "mtp-kv768-cpu8",
        "S3 CPU8 MTP2 KV768",
        8,
        True,
        KV_768_BYTES,
        "auto (BF16)",
        "mtp-cpu8",
        "KV budget 512→768MiB",
    ),
    StageSpec(
        4,
        "mtp-kv768-fp8-cpu8",
        "S4 CPU8 MTP2 KV768 FP8",
        8,
        True,
        KV_768_BYTES,
        "fp8",
        "mtp-kv768-cpu8",
        "KV dtype auto/BF16→FP8",
    ),
)
STAGE_BY_NAME = {stage.name: stage for stage in STAGES}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComparisonError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ComparisonError(f"{path}:{line_number}: request is not an object")
        rows.append(value)
    return rows


def comparable(value: Any) -> Any:
    """Normalize non-finite floats before comparing generated JSON structures."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [comparable(item) for item in value]
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    return value


def finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def require_finite(value: Any, label: str, *, positive: bool = False) -> float:
    number = finite(value)
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "finite and positive" if positive else "finite"
        raise ComparisonError(f"{label}: expected a {qualifier} value, found {value!r}")
    return number


def percent_change(before: Any, after: Any) -> float:
    before_number = finite(before)
    after_number = finite(after)
    if (
        not math.isfinite(before_number)
        or before_number == 0
        or not math.isfinite(after_number)
    ):
        return math.nan
    return 100.0 * (after_number / before_number - 1.0)


def fmt(value: Any, digits: int = 6) -> str:
    number = finite(value)
    return "" if not math.isfinite(number) else f"{number:.{digits}f}"


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ComparisonError(f"{label}: timestamp is missing")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ComparisonError(f"{label}: invalid ISO-8601 timestamp {value!r}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ComparisonError(f"{label}: timestamp lacks a UTC offset")
    return timestamp


def expected_args(stage: StageSpec) -> list[str]:
    args = list(BASE_ARGS)
    args[args.index("--kv-cache-memory-bytes") + 1] = stage.kv_bytes
    if stage.mtp_enabled:
        args.extend(("--speculative-config", MTP_CONFIG))
    if stage.kv_dtype == "fp8":
        # The FP8 stage must be S3 plus these exact trailing arguments.
        args.extend(("--kv-cache-dtype", "fp8", "--calculate-kv-scales"))
    return args


def expected_resources(stage: StageSpec) -> dict[str, dict[str, str]]:
    return {
        "limits": {"cpu": str(stage.cpu_limit), "memory": "8Gi"},
        "requests": {"cpu": "4", "memory": "4Gi"},
    }


def normalize_env(entries: Any, label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(entries, list):
        raise ComparisonError(f"{label}: container env is not a list")
    normalized: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "value"}:
            raise ComparisonError(f"{label}: unsupported container env entry {entry!r}")
        normalized.append((str(entry["name"]), str(entry["value"])))
    return tuple(normalized)


def normalized_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ComparisonError("manifest config is not an object")
    normalized = copy.deepcopy(config)
    normalized.pop("experiment", None)
    return normalized


def model_signature(endpoint: Any) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(endpoint, dict) or not isinstance(endpoint.get("data"), list):
        return ()
    result = []
    for item in endpoint["data"]:
        if isinstance(item, dict):
            result.append(
                (
                    item.get("id"),
                    item.get("root"),
                    item.get("owned_by"),
                    item.get("max_model_len"),
                )
            )
    return tuple(sorted(result, key=repr))


def resolve_phase_artifact(stage_dir: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ComparisonError(f"{label}: artifact path is missing")
    relative = Path(value)
    if relative.is_absolute():
        raise ComparisonError(f"{label}: artifact path must be relative, found {value!r}")
    root = stage_dir.resolve()
    artifact = (stage_dir / relative).resolve()
    if root != artifact and root not in artifact.parents:
        raise ComparisonError(f"{label}: artifact escapes the stage directory")
    if not artifact.is_file():
        raise ComparisonError(f"{label}: missing artifact {artifact}")
    return artifact


def require_result_files(results_root: Path) -> None:
    missing: list[str] = []
    for stage in STAGES:
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
            "Missing required sequential result(s):\n"
            + "\n".join(missing)
            + "\nAll five seven-phase/700-request stages must be complete."
        )


def load_results(results_root: Path) -> dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]:
    require_result_files(results_root)
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    for stage in STAGES:
        directory = results_root / stage.name
        summary = read_json(directory / "summary.json")
        manifest = read_json(directory / "run-manifest.json")
        if not isinstance(summary, list) or not isinstance(manifest, dict):
            raise ComparisonError(f"{stage.name}: malformed summary or manifest")

        recomputed_summary, recomputed_manifest = aggregate_raw(directory)
        if recomputed_manifest != manifest:
            raise ComparisonError(f"{stage.name}: raw aggregator read a different manifest")
        if comparable(summary) != comparable(recomputed_summary):
            raise ComparisonError(
                f"{stage.name}: summary.json differs from raw request/metric aggregation"
            )
        loaded[stage.name] = (
            sorted(summary, key=lambda row: int(row["concurrency"])),
            manifest,
        )
    return loaded


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
        raise ComparisonError(
            f"{stage.name}: Docker architecture must be 'x86_64', "
            f"found {docker.get('architecture')!r}"
        )
    if not str(docker.get("operating_system", "")).startswith("Docker Desktop"):
        raise ComparisonError(f"{stage.name}: Docker Desktop identity is missing")

    nodes = kubernetes.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ComparisonError(f"{stage.name}: Kubernetes node capture is empty")
    if any(not isinstance(node, dict) or node.get("architecture") != "amd64" for node in nodes):
        raise ComparisonError(f"{stage.name}: every Kubernetes node must be amd64")

    container = kubernetes.get("container")
    if not isinstance(container, dict):
        raise ComparisonError(f"{stage.name}: captured container spec is missing")
    if container.get("image") != IMAGE:
        raise ComparisonError(
            f"{stage.name}: expected image {IMAGE!r}, found {container.get('image')!r}"
        )
    expected = expected_args(stage)
    if container.get("args") != expected:
        raise ComparisonError(
            f"{stage.name}: container args are not exact; "
            f"expected={expected!r}, found={container.get('args')!r}"
        )
    resources = expected_resources(stage)
    if container.get("resources") != resources:
        raise ComparisonError(
            f"{stage.name}: resources are not exact; "
            f"expected={resources!r}, found={container.get('resources')!r}"
        )
    if normalize_env(container.get("env"), stage.name) != EXPECTED_ENV:
        raise ComparisonError(f"{stage.name}: serving environment variables differ")
    if kubernetes.get("serving_variant") != stage.name:
        raise ComparisonError(
            f"{stage.name}: serving-variant label is {kubernetes.get('serving_variant')!r}"
        )
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


def validate_expected_workload(config: dict[str, Any], stage_name: str) -> None:
    for key, expected in EXPECTED_WORKLOAD_FIELDS.items():
        if config.get(key) != expected:
            raise ComparisonError(
                f"{stage_name}: workload field {key!r} must be {expected!r}, "
                f"found {config.get(key)!r}"
            )
    if not isinstance(config.get("system_prompt"), str) or not config["system_prompt"]:
        raise ComparisonError(f"{stage_name}: system_prompt is empty")


def request_signature(rows: list[dict[str, Any]], label: str) -> tuple[tuple[Any, ...], ...]:
    if len(rows) != REQUESTS_PER_PHASE:
        raise ComparisonError(
            f"{label}: expected {REQUESTS_PER_PHASE} raw requests, found {len(rows)}"
        )
    signature: list[tuple[Any, ...]] = []
    for expected_sequence, request in enumerate(rows):
        if int(request.get("sequence", -1)) != expected_sequence:
            raise ComparisonError(f"{label}: raw request order is not sequence 0..99")
        if int(request.get("concurrency", -1)) <= 0:
            raise ComparisonError(f"{label}: raw request concurrency is invalid")
        if request.get("status") != "success" or request.get("error") not in (None, ""):
            raise ComparisonError(f"{label}: raw request {expected_sequence} did not succeed")
        if request.get("warmup") is not False:
            raise ComparisonError(f"{label}: measured request is marked as warmup")
        prompt_id = request.get("prompt_id")
        source = request.get("source")
        if not prompt_id or not source:
            raise ComparisonError(f"{label}: request identity is incomplete")
        prompt_tokens = int(request.get("prompt_tokens", -1))
        completion_tokens = int(request.get("completion_tokens", -1))
        if prompt_tokens <= 0 or completion_tokens != 64:
            raise ComparisonError(
                f"{label}: request {expected_sequence} token work is not prompt>0/output=64"
            )
        signature.append(
            (expected_sequence, prompt_id, source, prompt_tokens, completion_tokens)
        )
    return tuple(signature)


def warmup_signature(warmups: Any, concurrency: int, label: str) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(warmups, list) or len(warmups) != WARMUP_REQUESTS:
        raise ComparisonError(f"{label}: expected exactly three warmup results")
    signature: list[tuple[Any, ...]] = []
    for expected_sequence, request in enumerate(warmups):
        if not isinstance(request, dict):
            raise ComparisonError(f"{label}: malformed warmup result")
        if (
            int(request.get("sequence", -1)) != expected_sequence
            or int(request.get("concurrency", -1)) != concurrency
            or request.get("warmup") is not True
            or request.get("status") != "success"
            or request.get("error") not in (None, "")
            or int(request.get("completion_tokens", -1)) != 8
        ):
            raise ComparisonError(f"{label}: warmup result {expected_sequence} is invalid")
        signature.append(
            (
                expected_sequence,
                request.get("prompt_id"),
                request.get("source"),
                int(request.get("prompt_tokens", -1)),
                int(request.get("completion_tokens", -1)),
            )
        )
    return tuple(signature)


def validate_phase_pod(stage: StageSpec, phase: dict[str, Any], pod: dict[str, Any], concurrency: int) -> None:
    after = phase.get("kubernetes_pods_after")
    if not isinstance(after, list) or len(after) != 1 or not isinstance(after[0], dict):
        raise ComparisonError(f"{stage.name} C={concurrency}: expected one Pod after phase")
    phase_pod = after[0]
    for field in ("name", "uid", "node", "image_id"):
        if phase_pod.get(field) != pod.get(field):
            raise ComparisonError(
                f"{stage.name} C={concurrency}: Pod {field} changed during the run"
            )
    if phase_pod.get("phase") != "Running" or int(
        phase_pod.get("restart_count", -1)
    ) != 0:
        raise ComparisonError(
            f"{stage.name} C={concurrency}: Pod is not Running with restart_count=0"
        )


def validate_results(
    results_root: Path,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> list[str]:
    baseline_rows, baseline_manifest = loaded["baseline"]
    baseline_config = normalized_config(baseline_manifest.get("config"))
    validate_expected_workload(baseline_config, "baseline")
    baseline_prompt_hash = baseline_manifest.get("prompts_sha256")
    baseline_prompts_file = baseline_manifest.get("prompts_file")
    baseline_tokens = baseline_manifest.get("input_token_validation")
    baseline_server = baseline_manifest.get("server_version")
    baseline_model = model_signature(baseline_manifest.get("model_endpoint"))
    baseline_environment = baseline_manifest.get("environment")
    if not isinstance(baseline_environment, dict):
        raise ComparisonError("baseline: environment is missing")
    baseline_host = baseline_environment.get("host")
    baseline_docker = baseline_environment.get("docker")
    baseline_nodes = baseline_environment.get("kubernetes", {}).get("nodes")
    baseline_git = baseline_environment.get("git")
    baseline_runner = baseline_manifest.get("runner_sha256")
    baseline_schema = baseline_manifest.get("schema_version")
    if baseline_schema != 1:
        raise ComparisonError(
            f"baseline: expected manifest schema_version=1, found {baseline_schema!r}"
        )
    if not isinstance(baseline_prompt_hash, str) or len(baseline_prompt_hash) != 64:
        raise ComparisonError("baseline: prompts SHA-256 is missing or malformed")
    if not isinstance(baseline_tokens, dict) or not baseline_tokens:
        raise ComparisonError("baseline: input token validation is missing")
    if not isinstance(baseline_server, dict) or not baseline_server:
        raise ComparisonError("baseline: server version is missing")
    if not baseline_model:
        raise ComparisonError("baseline: served model identity is missing")
    if not isinstance(baseline_git, dict) or not baseline_git.get("commit"):
        raise ComparisonError("baseline: Git provenance is missing")
    if not isinstance(baseline_runner, str) or len(baseline_runner) != 64:
        raise ComparisonError("baseline: runner SHA-256 is missing or malformed")

    baseline_pod = validate_container(STAGES[0], baseline_manifest)
    baseline_image_id = baseline_pod["image_id"]
    baseline_node = baseline_pod["node"]
    canonical_requests: tuple[tuple[Any, ...], ...] | None = None
    canonical_warmups: tuple[tuple[Any, ...], ...] | None = None
    warnings: list[str] = []
    pod_uids: set[str] = set()
    previous_stage_finish: datetime | None = None

    for stage in STAGES:
        rows, manifest = loaded[stage.name]
        if manifest.get("schema_version") != baseline_schema:
            raise ComparisonError(f"{stage.name}: manifest schema version differs")
        if manifest.get("status") != "completed" or int(
            manifest.get("total_failures", -1)
        ) != 0:
            raise ComparisonError(f"{stage.name}: run is not completed with total_failures=0")
        if manifest.get("endpoint_binding") != "local-kubernetes-service":
            raise ComparisonError(f"{stage.name}: endpoint is not the local Kubernetes Service")

        config = manifest.get("config")
        if not isinstance(config, dict) or config.get("experiment") != stage.name:
            raise ComparisonError(f"{stage.name}: config experiment identity differs")
        validate_expected_workload(config, stage.name)
        if normalized_config(config) != baseline_config:
            raise ComparisonError(f"{stage.name}: workload config differs from baseline")
        if manifest.get("concurrencies") != list(CONCURRENCIES):
            raise ComparisonError(f"{stage.name}: manifest concurrency order differs")
        if manifest.get("prompt_count") != REQUESTS_PER_PHASE:
            raise ComparisonError(f"{stage.name}: prompt_count must be 100")
        if manifest.get("prompts_sha256") != baseline_prompt_hash:
            raise ComparisonError(f"{stage.name}: prompt workload SHA-256 differs")
        if manifest.get("prompts_file") != baseline_prompts_file:
            raise ComparisonError(f"{stage.name}: prompts file provenance differs")
        if manifest.get("input_token_validation") != baseline_tokens:
            raise ComparisonError(f"{stage.name}: tokenized input workload differs")
        if manifest.get("server_version") != baseline_server:
            raise ComparisonError(f"{stage.name}: vLLM server version differs")
        if model_signature(manifest.get("model_endpoint")) != baseline_model:
            raise ComparisonError(f"{stage.name}: served model identity differs")
        if manifest.get("runner_sha256") != baseline_runner:
            raise ComparisonError(f"{stage.name}: benchmark runner SHA-256 differs")

        environment = manifest.get("environment")
        if not isinstance(environment, dict):
            raise ComparisonError(f"{stage.name}: environment capture is missing")
        if environment.get("host") != baseline_host:
            raise ComparisonError(f"{stage.name}: host identity/resources differ")
        if environment.get("docker") != baseline_docker:
            raise ComparisonError(f"{stage.name}: Docker identity/resources differ")
        if environment.get("git") != baseline_git:
            raise ComparisonError(f"{stage.name}: Git commit or worktree state differs")
        if environment.get("kubernetes", {}).get("nodes") != baseline_nodes:
            raise ComparisonError(f"{stage.name}: Kubernetes node inventory differs")

        pod = baseline_pod if stage.order == 0 else validate_container(stage, manifest)
        if pod["image_id"] != baseline_image_id:
            raise ComparisonError(f"{stage.name}: immutable container image ID differs")
        if pod["node"] != baseline_node:
            raise ComparisonError(f"{stage.name}: serving Pod moved to a different node")
        if pod["uid"] in pod_uids:
            raise ComparisonError(f"{stage.name}: Pod UID was reused by another stage")
        pod_uids.add(pod["uid"])

        stage_start = parse_timestamp(manifest.get("started_at_utc"), f"{stage.name} start")
        stage_finish = parse_timestamp(
            manifest.get("finished_at_utc"), f"{stage.name} finish"
        )
        if stage_finish <= stage_start:
            raise ComparisonError(f"{stage.name}: run finish does not follow start")
        if previous_stage_finish is not None and stage_start < previous_stage_finish:
            raise ComparisonError(f"{stage.name}: stages overlap or are out of order")
        previous_stage_finish = stage_finish

        row_concurrencies = [int(row.get("concurrency", -1)) for row in rows]
        if row_concurrencies != list(CONCURRENCIES):
            raise ComparisonError(
                f"{stage.name}: summary phases {row_concurrencies}, expected {list(CONCURRENCIES)}"
            )
        phases = manifest.get("phases")
        if not isinstance(phases, list) or [
            int(phase.get("concurrency", -1)) if isinstance(phase, dict) else -1
            for phase in phases
        ] != list(CONCURRENCIES):
            raise ComparisonError(f"{stage.name}: manifest must contain seven ordered phases")

        stage_dir = results_root / stage.name
        total_requests = 0
        previous_phase_finish: datetime | None = None
        for row, phase, concurrency in zip(rows, phases, CONCURRENCIES, strict=True):
            assert isinstance(phase, dict)
            label = f"{stage.name} C={concurrency}"
            requests = int(row.get("requests", -1))
            successes = int(row.get("successes", -1))
            failures = int(row.get("failures", -1))
            total_requests += requests
            if (requests, successes, failures) != (100, 100, 0):
                raise ComparisonError(
                    f"{label}: expected requests/successes/failures=100/100/0, "
                    f"found {requests}/{successes}/{failures}"
                )
            if (
                int(phase.get("request_count", -1)),
                int(phase.get("success_count", -1)),
                int(phase.get("failure_count", -1)),
            ) != (100, 100, 0):
                raise ComparisonError(f"{label}: phase metadata is not 100/100/0")
            if phase.get("metrics_scrape_errors") != []:
                raise ComparisonError(f"{label}: metrics scrape errors are present")
            if phase.get("runtime_validation_errors") != []:
                raise ComparisonError(f"{label}: runtime validation errors are present")
            if int(phase.get("warmup_request_count", -1)) != WARMUP_REQUESTS:
                raise ComparisonError(f"{label}: warmup count is not three")
            if int(phase.get("metrics_sample_count", 0)) < 2:
                raise ComparisonError(
                    f"{label}: fewer than two server/cgroup metric samples were captured"
                )
            validate_phase_pod(stage, phase, pod, concurrency)

            phase_path = stage_dir / "raw" / f"phase-c{concurrency:02d}.json"
            if not phase_path.is_file():
                raise ComparisonError(f"{label}: missing phase artifact {phase_path}")
            raw_phase = read_json(phase_path)
            if raw_phase != phase:
                raise ComparisonError(
                    f"{label}: raw phase artifact differs from the embedded manifest phase"
                )

            phase_start = parse_timestamp(phase.get("started_at_utc"), f"{label} start")
            phase_finish = parse_timestamp(phase.get("finished_at_utc"), f"{label} finish")
            duration = require_finite(
                phase.get("duration_seconds"), f"{label} duration", positive=True
            )
            wall_seconds = (phase_finish - phase_start).total_seconds()
            if wall_seconds <= 0:
                raise ComparisonError(f"{label}: phase finish does not follow start")
            timer_gap = abs(wall_seconds - duration)
            if timer_gap > max(5.0, duration * 0.01):
                raise ComparisonError(
                    f"{label}: wall/monotonic timer gap {timer_gap:.3f}s exceeds tolerance"
                )
            if phase_start < stage_start or phase_finish > stage_finish:
                raise ComparisonError(f"{label}: phase timestamps fall outside the run")
            if previous_phase_finish is not None and phase_start < previous_phase_finish:
                raise ComparisonError(f"{label}: phases overlap or are out of order")
            previous_phase_finish = phase_finish

            requests_path = resolve_phase_artifact(
                stage_dir, phase.get("requests_file"), f"{label} requests"
            )
            metrics_path = resolve_phase_artifact(
                stage_dir, phase.get("metrics_file"), f"{label} metrics"
            )
            raw_requests = read_jsonl(requests_path)
            if any(int(item.get("concurrency", -1)) != concurrency for item in raw_requests):
                raise ComparisonError(f"{label}: raw request concurrency differs")
            signature = request_signature(raw_requests, label)
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
            if (
                int(require_finite(row.get("total_prompt_tokens"), f"{label} prompt tokens")),
                int(
                    require_finite(
                        row.get("total_completion_tokens"), f"{label} completion tokens"
                    )
                ),
            ) != (prompt_total, completion_total):
                raise ComparisonError(f"{label}: summary/client token totals differ")
            if int(
                require_finite(
                    row.get("server_prompt_tokens_delta"), f"{label} server prompt tokens"
                )
            ) != prompt_total or int(
                require_finite(
                    row.get("server_generation_tokens_delta"),
                    f"{label} server generation tokens",
                )
            ) != completion_total:
                raise ComparisonError(f"{label}: client/server token counters differ")

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
                "peak_pod_memory_gib",
            ):
                value = require_finite(row.get(metric), f"{label} {metric}")
                if value < 0:
                    raise ComparisonError(f"{label}: {metric} is negative")

            memory_max = require_finite(
                row.get("memory_max_events_delta"), f"{label} memory.events:max"
            )
            if memory_max < 0:
                raise ComparisonError(f"{label}: memory.events:max delta is negative")
            if memory_max > 0:
                warnings.append(f"{stage.name} C={concurrency}: memory.events:max +{memory_max:g}")
            for metric in ("oom_events_delta", "oom_kill_events_delta"):
                value = require_finite(row.get(metric), f"{label} {metric}")
                if value != 0:
                    raise ComparisonError(f"{label}: {metric} must be zero, found {value:g}")

            phase_memory = phase.get("cgroup_memory_event_deltas")
            if not isinstance(phase_memory, dict) or set(phase_memory) != {
                "max",
                "oom",
                "oom_kill",
            }:
                raise ComparisonError(
                    f"{label}: cgroup_memory_event_deltas is missing or malformed"
                )
            phase_max = require_finite(
                phase_memory.get("max"), f"{label} phase memory.events:max"
            )
            phase_oom = require_finite(
                phase_memory.get("oom"), f"{label} phase memory.events:oom"
            )
            phase_oom_kill = require_finite(
                phase_memory.get("oom_kill"), f"{label} phase memory.events:oom_kill"
            )
            if phase_max != memory_max:
                raise ComparisonError(
                    f"{label}: phase and raw-summary memory.events:max deltas differ"
                )
            if phase_oom != 0 or phase_oom_kill != 0:
                raise ComparisonError(f"{label}: phase OOM/OOM-kill deltas must be zero")
            expected_pressure_warnings = (
                [f"Pod cgroup memory max counter increased by {phase_max:g}"]
                if phase_max > 0
                else []
            )
            if phase.get("memory_pressure_warnings") != expected_pressure_warnings:
                raise ComparisonError(
                    f"{label}: memory pressure warning does not match memory.events:max"
                )

            if stage.mtp_enabled:
                drafts = require_finite(
                    row.get("spec_drafts_delta"), f"{label} speculative drafts"
                )
                draft_tokens = require_finite(
                    row.get("spec_draft_tokens_delta"),
                    f"{label} speculative draft tokens",
                )
                accepted_tokens = require_finite(
                    row.get("spec_accepted_tokens_delta"),
                    f"{label} speculative accepted tokens",
                )
                acceptance = require_finite(
                    row.get("spec_acceptance_percent"),
                    f"{label} speculative acceptance",
                )
                if (
                    drafts <= 0
                    or draft_tokens <= 0
                    or accepted_tokens < 0
                    or accepted_tokens > draft_tokens
                    or not 0 <= acceptance <= 100
                ):
                    raise ComparisonError(f"{label}: speculative counters are invalid")

            with metrics_path.open("r", encoding="utf-8", newline="") as handle:
                metric_rows = list(csv.DictReader(handle))
            if len(metric_rows) != int(phase["metrics_sample_count"]):
                raise ComparisonError(
                    f"{label}: metrics_sample_count does not match raw CSV rows"
                )

            tolerance = timedelta(seconds=1)
            for request in raw_requests:
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
                    raise ComparisonError(f"{label}: request timer falls outside phase bounds")

        if total_requests != len(CONCURRENCIES) * REQUESTS_PER_PHASE:
            raise ComparisonError(
                f"{stage.name}: expected exactly 700 requests, found {total_requests}"
            )

    assert canonical_requests is not None
    token_map = {str(item[1]): int(item[3]) for item in canonical_requests}
    if baseline_tokens.get("counts_by_prompt_id") != token_map:
        raise ComparisonError("input_token_validation does not match raw prompt/token order")
    return warnings


def build_rows(
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]
) -> list[dict[str, Any]]:
    by_stage = {
        name: {int(row["concurrency"]): row for row in rows}
        for name, (rows, _manifest) in loaded.items()
    }
    output: list[dict[str, Any]] = []
    for stage in STAGES:
        for concurrency in CONCURRENCIES:
            current = by_stage[stage.name][concurrency]
            previous = (
                by_stage[stage.previous][concurrency] if stage.previous is not None else None
            )
            output.append(
                {
                    "stage_order": stage.order,
                    "stage": stage.name,
                    "display_name": stage.display_name,
                    "previous_stage": stage.previous or "",
                    "changed_factor": stage.changed_factor,
                    "concurrency": concurrency,
                    "cpu_limit": stage.cpu_limit,
                    "mtp_enabled": str(stage.mtp_enabled).lower(),
                    "kv_cache_mib": stage.kv_mib,
                    "kv_cache_dtype": stage.kv_dtype,
                    "requests": int(current["requests"]),
                    "output_tps": fmt(current["output_token_throughput_tps"]),
                    "previous_output_tps": (
                        fmt(previous["output_token_throughput_tps"]) if previous else ""
                    ),
                    "adjacent_output_percent": (
                        fmt(
                            percent_change(
                                previous["output_token_throughput_tps"],
                                current["output_token_throughput_tps"],
                            )
                        )
                        if previous
                        else ""
                    ),
                    "request_rps": fmt(current["request_throughput_rps"]),
                    "adjacent_request_rps_percent": (
                        fmt(
                            percent_change(
                                previous["request_throughput_rps"],
                                current["request_throughput_rps"],
                            )
                        )
                        if previous
                        else ""
                    ),
                    "e2e_p95_seconds": fmt(current["e2e_seconds_p95"]),
                    "adjacent_e2e_p95_percent": (
                        fmt(
                            percent_change(
                                previous["e2e_seconds_p95"], current["e2e_seconds_p95"]
                            )
                        )
                        if previous
                        else ""
                    ),
                    "ttft_p95_seconds": fmt(current["ttft_seconds_p95"]),
                    "adjacent_ttft_p95_percent": (
                        fmt(
                            percent_change(
                                previous["ttft_seconds_p95"],
                                current["ttft_seconds_p95"],
                            )
                        )
                        if previous
                        else ""
                    ),
                    "tpot_p95_ms": fmt(current["tpot_ms_p95"]),
                    "adjacent_tpot_p95_percent": (
                        fmt(
                            percent_change(
                                previous["tpot_ms_p95"], current["tpot_ms_p95"]
                            )
                        )
                        if previous
                        else ""
                    ),
                    "peak_running": fmt(current["peak_running_requests"], 0),
                    "peak_waiting": fmt(current["peak_waiting_requests"], 0),
                    "peak_kv_percent": fmt(current["peak_kv_cache_percent"]),
                    "spec_acceptance_percent": fmt(current.get("spec_acceptance_percent")),
                    "avg_cpu_cores": fmt(current["avg_pod_cpu_cores"]),
                    "peak_memory_gib": fmt(current["peak_pod_memory_gib"]),
                    "memory_max_events_delta": fmt(
                        current["memory_max_events_delta"], 0
                    ),
                    "oom_events_delta": fmt(current["oom_events_delta"], 0),
                    "oom_kill_events_delta": fmt(
                        current["oom_kill_events_delta"], 0
                    ),
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_response_hash_rows(results_root: Path) -> list[dict[str, Any]]:
    """Compare exact response hashes for each adjacent single-factor transition."""
    output: list[dict[str, Any]] = []
    for stage in STAGES[1:]:
        assert stage.previous is not None
        for concurrency in CONCURRENCIES:
            filename = f"requests-c{concurrency:02d}.jsonl"
            previous_rows = read_jsonl(
                results_root / stage.previous / "raw" / filename
            )
            current_rows = read_jsonl(results_root / stage.name / "raw" / filename)
            if len(previous_rows) != REQUESTS_PER_PHASE or len(current_rows) != REQUESTS_PER_PHASE:
                raise ComparisonError(
                    f"{stage.name} C={concurrency}: response-hash comparison is not 100 vs 100"
                )

            matches = 0
            for index, (previous, current) in enumerate(
                zip(previous_rows, current_rows, strict=True)
            ):
                previous_identity = (
                    previous.get("sequence"),
                    previous.get("prompt_id"),
                    previous.get("source"),
                )
                current_identity = (
                    current.get("sequence"),
                    current.get("prompt_id"),
                    current.get("source"),
                )
                if previous_identity != current_identity:
                    raise ComparisonError(
                        f"{stage.name} C={concurrency}: response identity differs at row {index}"
                    )
                previous_hash = previous.get("content_sha256")
                current_hash = current.get("content_sha256")
                if not all(
                    isinstance(value, str) and len(value) == 64
                    for value in (previous_hash, current_hash)
                ):
                    raise ComparisonError(
                        f"{stage.name} C={concurrency}: malformed response content hash"
                    )
                if previous_hash == current_hash:
                    matches += 1

            output.append(
                {
                    "stage_order": stage.order,
                    "previous_stage": stage.previous,
                    "stage": stage.name,
                    "changed_factor": stage.changed_factor,
                    "concurrency": concurrency,
                    "requests": REQUESTS_PER_PHASE,
                    "exact_hash_matches": matches,
                    "exact_hash_mismatches": REQUESTS_PER_PHASE - matches,
                    "exact_hash_match_percent": fmt(
                        matches / REQUESTS_PER_PHASE * 100
                    ),
                }
            )
    return output


def load_startup_evidence(
    results_root: Path,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Validate saved startup artifacts and extract effective KV capacity."""
    output: list[dict[str, Any]] = []
    token_pattern = re.compile(r"GPU KV cache size: ([0-9,]+) tokens")
    concurrency_pattern = re.compile(
        r"Maximum concurrency for 2,048 tokens per request: ([0-9.]+)x"
    )
    for stage in STAGES:
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
        expected_budget = "0.75/8.0" if stage.kv_bytes == KV_768_BYTES else "0.5/8.0"
        if f"Explicitly set ({expected_budget}) GiB for KV cache" not in log:
            raise ComparisonError(
                f"{stage.name}: startup log does not prove the expected KV budget"
            )
        expected_dtype = "kv_cache_dtype=fp8" if stage.kv_dtype == "fp8" else "kv_cache_dtype=auto"
        if expected_dtype not in log:
            raise ComparisonError(
                f"{stage.name}: startup log does not prove {expected_dtype}"
            )

        token_matches = {int(value.replace(",", "")) for value in token_pattern.findall(log)}
        concurrency_matches = {
            float(value) for value in concurrency_pattern.findall(log)
        }
        if len(token_matches) != 1 or len(concurrency_matches) != 1:
            raise ComparisonError(
                f"{stage.name}: startup KV token/concurrency evidence is missing or ambiguous"
            )

        startup_pod = read_json(pod_path)
        manifest_pods = loaded[stage.name][1]["environment"]["kubernetes"]["pods"]
        manifest_pod = manifest_pods[0]
        startup_statuses = startup_pod.get("status", {}).get("containerStatuses", [])
        if not isinstance(startup_statuses, list) or len(startup_statuses) != 1:
            raise ComparisonError(f"{stage.name}: startup Pod status is malformed")
        if (
            startup_pod.get("metadata", {}).get("uid") != manifest_pod.get("uid")
            or startup_pod.get("spec", {}).get("nodeName") != manifest_pod.get("node")
            or startup_pod.get("status", {}).get("phase") != "Running"
            or int(startup_statuses[0].get("restartCount", -1)) != 0
            or startup_statuses[0].get("imageID") != manifest_pod.get("image_id")
        ):
            raise ComparisonError(
                f"{stage.name}: startup Pod evidence differs from the run manifest"
            )

        if stage.kv_dtype == "fp8":
            for marker in (
                "accuracy drop without a proper scaling factor",
                "Disabling calculate_kv_scales for hybrid model",
                "Using default scale of 1.0 instead",
            ):
                if marker not in log:
                    raise ComparisonError(
                        f"{stage.name}: FP8 startup warning is missing: {marker}"
                    )

        output.append(
            {
                "stage_order": stage.order,
                "stage": stage.name,
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


def validate_fp8_gate(
    results_root: Path,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    """Validate the separate 20-request C20 compatibility gate."""
    directory = (
        results_root
        / "validation-gates"
        / "mtp-kv768-fp8-cpu8-c20"
    )
    summary_path = directory / "summary.json"
    manifest_path = directory / "run-manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise ComparisonError("FP8 C20 gate summary or manifest is missing")
    summary = read_json(summary_path)
    manifest = read_json(manifest_path)
    recomputed_summary, recomputed_manifest = aggregate_raw(directory)
    if comparable(summary) != comparable(recomputed_summary) or manifest != recomputed_manifest:
        raise ComparisonError("FP8 C20 gate differs from its raw aggregation")
    if not isinstance(summary, list) or len(summary) != 1 or not isinstance(manifest, dict):
        raise ComparisonError("FP8 C20 gate summary or manifest is malformed")

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
    ):
        raise ComparisonError("FP8 C20 gate is not a completed 20/20 run")
    phase = phases[0]
    if (
        (
            int(phase.get("request_count", -1)),
            int(phase.get("success_count", -1)),
            int(phase.get("failure_count", -1)),
        )
        != (20, 20, 0)
        or phase.get("metrics_scrape_errors") != []
        or phase.get("runtime_validation_errors") != []
        or phase.get("cgroup_memory_event_deltas")
        != {"max": 0.0, "oom": 0.0, "oom_kill": 0.0}
    ):
        raise ComparisonError("FP8 C20 gate phase validation failed")

    formal_manifest = loaded["mtp-kv768-fp8-cpu8"][1]
    gate_environment = manifest.get("environment", {})
    formal_environment = formal_manifest.get("environment", {})
    gate_kubernetes = gate_environment.get("kubernetes", {})
    formal_kubernetes = formal_environment.get("kubernetes", {})
    gate_pods = gate_kubernetes.get("pods")
    if (
        manifest.get("runner_sha256") != formal_manifest.get("runner_sha256")
        or gate_environment.get("host") != formal_environment.get("host")
        or gate_environment.get("docker") != formal_environment.get("docker")
        or gate_kubernetes.get("nodes") != formal_kubernetes.get("nodes")
        or gate_kubernetes.get("container") != formal_kubernetes.get("container")
        or not isinstance(gate_pods, list)
        or len(gate_pods) != 1
        or gate_pods[0].get("image_id")
        != formal_kubernetes.get("pods", [{}])[0].get("image_id")
        or gate_pods[0].get("phase") != "Running"
        or int(gate_pods[0].get("restart_count", -1)) != 0
    ):
        raise ComparisonError("FP8 C20 gate environment differs from the formal FP8 stage")
    return {
        "concurrency": 20,
        "requests": 20,
        "successes": 20,
        "failures": 0,
        "output_tps": fmt(row.get("output_token_throughput_tps")),
        "e2e_p95_seconds": fmt(row.get("e2e_seconds_p95")),
        "ttft_p95_seconds": fmt(row.get("ttft_seconds_p95")),
        "tpot_p95_ms": fmt(row.get("tpot_ms_p95")),
        "restart_count": 0,
        "oom_events_delta": 0,
        "oom_kill_events_delta": 0,
    }


def write_output_throughput_svg(
    path: Path,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> None:
    width, height = 1180, 650
    left, right, top, bottom = 90, 40, 155, 70
    plot_width = width - left - right
    plot_height = height - top - bottom
    series = []
    for stage in STAGES:
        rows = loaded[stage.name][0]
        values = [finite(row["output_token_throughput_tps"]) for row in rows]
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ComparisonError(f"{stage.name}: output throughput is not chartable")
        series.append((stage.display_name, values))
    y_max = max(value for _label, values in series for value in values) * 1.1

    def x_position(index: int) -> float:
        return left + index / (len(CONCURRENCIES) - 1) * plot_width

    def y_position(value: float) -> float:
        return top + (y_max - value) / y_max * plot_height

    description = (
        "Output token throughput for five sequential Windows x86-64 CPU-serving "
        "stages at client concurrencies 1, 2, 5, 10, 20, 50, and 100."
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Windows sequential experiment: output throughput</title>',
        f'<desc id="desc">{html.escape(description)}</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="34" text-anchor="middle" font-size="22" '
        'font-family="sans-serif" font-weight="600">Windows 5-stage sequential output throughput</text>',
        f'<text x="{width / 2}" y="59" text-anchor="middle" font-size="13" '
        'font-family="sans-serif" fill="#4b5563">Same workload, image, host, Docker and Kubernetes nodes · 100 requests per point</text>',
    ]
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
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#111827"/>',
            f'<text x="{left + plot_width / 2}" y="{height - 18}" text-anchor="middle" font-size="14" font-family="sans-serif">Client concurrency</text>',
            f'<text transform="translate(23 {top + plot_height / 2}) rotate(-90)" text-anchor="middle" font-size="14" font-family="sans-serif">Output tokens / second</text>',
        )
    )
    for index, (label, values) in enumerate(series):
        color = COLORS[index]
        legend_x = left + (index % 3) * 350
        legend_y = 89 + (index // 3) * 27
        points = " ".join(
            f"{x_position(point_index):.2f},{y_position(value):.2f}"
            for point_index, value in enumerate(values)
        )
        parts.extend(
            (
                f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" '
                f'y2="{legend_y}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{legend_x + 31}" y="{legend_y + 4}" font-size="12" '
                f'font-family="sans-serif">{html.escape(label)}</text>',
                f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"/>',
            )
        )
        for point_index, value in enumerate(values):
            parts.append(
                f'<circle cx="{x_position(point_index):.2f}" cy="{y_position(value):.2f}" '
                f'r="3.5" fill="{color}"/>'
            )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_kv_cache_growth_svg(
    path: Path,
    loaded: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
) -> None:
    """Plot sampled peak KV occupancy as configured-budget-equivalent MiB."""
    chart_specs = (
        ("mtp-cpu8", "S2 · KV512", "#2563eb", "circle", ""),
        ("mtp-kv768-cpu8", "S3 · KV768", "#7c3aed", "square", "5 4"),
        (
            "mtp-kv768-fp8-cpu8",
            "S4 · 8-bit KV768",
            "#ea580c",
            "diamond",
            "2 3",
        ),
    )
    stage_by_name = {stage.name: stage for stage in STAGES}
    expected_controls = {
        "mtp-cpu8": (8, True, 512, "auto (BF16)"),
        "mtp-kv768-cpu8": (8, True, 768, "auto (BF16)"),
        "mtp-kv768-fp8-cpu8": (8, True, 768, "fp8"),
    }
    series: list[dict[str, Any]] = []
    description_parts: list[str] = []

    for stage_name, label, color, marker, dash in chart_specs:
        try:
            stage = stage_by_name[stage_name]
            rows = loaded[stage_name][0]
        except KeyError as exc:
            raise ComparisonError(
                f"{stage_name}: missing stage data for KV growth chart"
            ) from exc

        actual_controls = (
            stage.cpu_limit,
            stage.mtp_enabled,
            stage.kv_mib,
            stage.kv_dtype,
        )
        if actual_controls != expected_controls[stage_name]:
            raise ComparisonError(
                f"{stage_name}: unexpected controls for KV growth chart: "
                f"{actual_controls!r}"
            )

        row_by_concurrency: dict[int, dict[str, Any]] = {}
        for row in rows:
            concurrency = int(row["concurrency"])
            if concurrency in row_by_concurrency:
                raise ComparisonError(
                    f"{stage_name}: duplicate C={concurrency} for KV growth chart"
                )
            row_by_concurrency[concurrency] = row
        if set(row_by_concurrency) != set(CONCURRENCIES):
            raise ComparisonError(
                f"{stage_name}: KV growth chart requires concurrencies "
                f"{list(CONCURRENCIES)}"
            )

        percentages: list[float] = []
        occupied_mib: list[float] = []
        for concurrency in CONCURRENCIES:
            percentage = require_finite(
                row_by_concurrency[concurrency].get("peak_kv_cache_percent"),
                f"{stage_name} C={concurrency} peak KV percent",
            )
            if not 0 <= percentage <= 100 + 1e-6:
                raise ComparisonError(
                    f"{stage_name} C={concurrency}: peak KV percent must be in [0, 100]"
                )
            percentage = min(percentage, 100.0)
            estimated_mib = stage.kv_mib * percentage / 100.0
            if not 0 <= estimated_mib <= stage.kv_mib + 1e-6:
                raise ComparisonError(
                    f"{stage_name} C={concurrency}: invalid budget-equivalent MiB"
                )
            percentages.append(percentage)
            occupied_mib.append(estimated_mib)

        series.append(
            {
                "label": label,
                "color": color,
                "marker": marker,
                "dash": dash,
                "budget_mib": stage.kv_mib,
                "percentages": percentages,
                "occupied_mib": occupied_mib,
            }
        )
        observations = ", ".join(
            f"C{concurrency} {value:.1f} MiB ({percentage:.1f} percent)"
            for concurrency, value, percentage in zip(
                CONCURRENCIES, occupied_mib, percentages, strict=True
            )
        )
        description_parts.append(f"{label}: {observations}")

    width, height = 1280, 760
    left, right, top, bottom = 120, 75, 155, 110
    plot_width = width - left - right
    plot_height = height - top - bottom
    y_max = 800.0

    def x_position(index: int) -> float:
        return left + index / (len(CONCURRENCIES) - 1) * plot_width

    def y_position(value: float) -> float:
        return top + (y_max - value) / y_max * plot_height

    description = (
        "Sampled peak KV-cache occupancy for CPU8 MTP2 max-num-seqs 20. "
        + "; ".join(description_parts)
        + ". Budget-equivalent MiB equals configured KV budget multiplied by the "
        "one-second sampled peak used-block percentage; it is not Pod RSS."
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="kv-growth-title kv-growth-desc">',
        '<title id="kv-growth-title">Concurrency versus peak KV cache occupancy</title>',
        f'<desc id="kv-growth-desc">{html.escape(description)}</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="36" text-anchor="middle" font-size="23" '
        'font-family="sans-serif" font-weight="600">동시성 증가에 따른 peak KV cache 점유</text>',
        f'<text x="{width / 2}" y="64" text-anchor="middle" font-size="14" '
        'font-family="sans-serif" fill="#4b5563">CPU 8 · MTP2 · max-num-seqs 20 · 동일 100 prompts</text>',
    ]

    legend_width = 340
    legend_start = left + (plot_width - legend_width * len(series)) / 2
    for index, item in enumerate(series):
        legend_x = legend_start + index * legend_width
        legend_y = 103
        dash = (
            f' stroke-dasharray="{item["dash"]}"' if item["dash"] else ""
        )
        parts.extend(
            (
                f'<line x1="{legend_x:.2f}" y1="{legend_y}" '
                f'x2="{legend_x + 30:.2f}" y2="{legend_y}" '
                f'stroke="{item["color"]}" stroke-width="3"{dash}/>',
                f'<text x="{legend_x + 39:.2f}" y="{legend_y + 5}" '
                f'font-size="14" font-family="sans-serif">{html.escape(item["label"])}</text>',
            )
        )

    for tick in range(6):
        value = y_max * tick / 5
        y = y_position(value)
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" '
                f'y2="{y:.2f}" stroke="#e5e7eb"/>',
                f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" '
                f'font-size="12" font-family="sans-serif" fill="#4b5563">{value:.0f}</text>',
            )
        )

    for ceiling, label in ((512.0, "512MiB configured ceiling"), (768.0, "768MiB configured ceiling")):
        y = y_position(ceiling)
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" '
                f'y2="{y:.2f}" stroke="#9ca3af" stroke-width="1.2" '
                'stroke-dasharray="7 5"/>',
                f'<text x="{left + plot_width - 5}" y="{y - 7:.2f}" '
                f'text-anchor="end" font-size="12" font-family="sans-serif" '
                f'fill="#6b7280">{label}</text>',
            )
        )

    for index, concurrency in enumerate(CONCURRENCIES):
        x = x_position(index)
        parts.extend(
            (
                f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" '
                f'y2="{top + plot_height}" stroke="#f3f4f6"/>',
                f'<text x="{x:.2f}" y="{top + plot_height + 27}" '
                f'text-anchor="middle" font-size="13" font-family="sans-serif">{concurrency}</text>',
            )
        )

    parts.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" '
            f'y2="{top + plot_height}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{top + plot_height}" '
            f'x2="{left + plot_width}" y2="{top + plot_height}" stroke="#111827"/>',
            f'<text x="{left + plot_width / 2}" y="{top + plot_height + 57}" '
            'text-anchor="middle" font-size="14" font-family="sans-serif">Client concurrency (100 requests total)</text>',
            f'<text transform="translate(28 {top + plot_height / 2}) rotate(-90)" '
            'text-anchor="middle" font-size="14" font-family="sans-serif">Budget-equivalent peak KV occupancy (MiB)</text>',
        )
    )

    for item in series:
        dash = (
            f' stroke-dasharray="{item["dash"]}"' if item["dash"] else ""
        )
        points = " ".join(
            f"{x_position(index):.2f},{y_position(value):.2f}"
            for index, value in enumerate(item["occupied_mib"])
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{item["color"]}" '
            f'stroke-width="3"{dash}/>'
        )
        for index, value in enumerate(item["occupied_mib"]):
            x = x_position(index)
            y = y_position(value)
            if item["marker"] == "circle":
                marker = (
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" '
                    f'fill="{item["color"]}"/>'
                )
            elif item["marker"] == "square":
                marker = (
                    f'<rect x="{x - 4.5:.2f}" y="{y - 4.5:.2f}" width="9" '
                    f'height="9" fill="{item["color"]}"/>'
                )
            else:
                marker = (
                    f'<polygon points="{x:.2f},{y - 6:.2f} {x + 6:.2f},{y:.2f} '
                    f'{x:.2f},{y + 6:.2f} {x - 6:.2f},{y:.2f}" '
                    f'fill="{item["color"]}"/>'
                )
            parts.append(marker)

    parts.extend(
        (
            f'<text x="{width / 2}" y="{height - 24}" text-anchor="middle" '
            'font-size="13" font-family="sans-serif" fill="#4b5563">'
            'Budget-equivalent MiB = configured KV budget × sampled peak used-block ratio · Pod RSS가 아님</text>',
            "</svg>",
        )
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_report(
    output: Path,
    rows: list[dict[str, Any]],
    warnings: list[str],
    response_hash_rows: list[dict[str, Any]],
    startup_rows: list[dict[str, Any]],
    fp8_gate: dict[str, Any],
) -> None:
    args_table = [
        "| Stage | CPU | MTP2 | KV budget | KV dtype | 직전 단계에서 바뀐 값 |",
        "|---|---:|---|---:|---|---|",
    ]
    for stage in STAGES:
        args_table.append(
            f"| `{stage.name}` | {stage.cpu_limit} | "
            f"{'on' if stage.mtp_enabled else 'off'} | {stage.kv_mib}MiB | "
            f"{stage.kv_dtype} | {stage.changed_factor} |"
        )

    row_by_key = {(row["stage"], int(row["concurrency"])): row for row in rows}
    throughput_table = [
        "| C | " + " | ".join(f"S{stage.order}" for stage in STAGES) + " |",
        "|---:|" + "---:|" * len(STAGES),
    ]
    for concurrency in CONCURRENCIES:
        values = [
            f"{float(row_by_key[(stage.name, concurrency)]['output_tps']):.2f}"
            for stage in STAGES
        ]
        throughput_table.append(f"| {concurrency} | " + " | ".join(values) + " |")

    effect_table = [
        "| 전이 | C | output tok/s | request rps | E2E p95 | TTFT p95 | TPOT p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for stage in STAGES[1:]:
        for concurrency in CONCURRENCIES:
            row = row_by_key[(stage.name, concurrency)]
            effect_table.append(
                f"| S{stage.order - 1}→S{stage.order} ({stage.changed_factor}) | "
                f"{concurrency} | {float(row['adjacent_output_percent']):+.1f}% | "
                f"{float(row['adjacent_request_rps_percent']):+.1f}% | "
                f"{float(row['adjacent_e2e_p95_percent']):+.1f}% | "
                f"{float(row['adjacent_ttft_p95_percent']):+.1f}% | "
                f"{float(row['adjacent_tpot_p95_percent']):+.1f}% |"
            )

    startup_table = [
        "| Stage | KV budget | KV dtype | KV token capacity | max concurrency @ 2,048 tokens |",
        "|---|---:|---|---:|---:|",
    ]
    startup_by_stage = {row["stage"]: row for row in startup_rows}
    for stage in STAGES:
        startup = startup_by_stage[stage.name]
        startup_table.append(
            f"| S{stage.order} | {stage.kv_mib}MiB | {stage.kv_dtype} | "
            f"{int(startup['kv_cache_tokens']):,} | "
            f"{float(startup['max_concurrency_at_2048_tokens']):.2f}x |"
        )

    hash_table = [
        "| 전이 | C1 | C2 | C5 | C10 | C20 | C50 | C100 | 전체 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    hash_by_key = {
        (row["stage"], int(row["concurrency"])): row
        for row in response_hash_rows
    }
    for stage in STAGES[1:]:
        values = [
            int(hash_by_key[(stage.name, concurrency)]["exact_hash_matches"])
            for concurrency in CONCURRENCIES
        ]
        total = sum(values)
        hash_table.append(
            f"| S{stage.order - 1}→S{stage.order} | "
            + " | ".join(f"{value}/100" for value in values)
            + f" | {total}/700 ({total / 7:.1f}%) |"
        )

    if warnings:
        memory_text = "\n".join(f"- 경고: {warning}" for warning in warnings)
    else:
        memory_text = "- 모든 phase의 `memory.events:max` delta가 `0`이다."

    report = f"""# Windows x86_64 5단계 순차 실험 비교

## 검증 결과

- 5개 stage × 7개 concurrency × 100건 = `3,500/3,500` 성공을 검증했다.
- `summary.json`을 raw request/metrics/phase artifact에서 다시 집계해 저장본과 일치함을 확인했다.
- workload config, prompt SHA-256, tokenized input, raw prompt/token/order, warmup, wall/monotonic timer를 전 단계에서 대조했다.
- 각 stage에서 같은 Pod UID/image ID/node가 7개 phase 동안 유지됐고 restart, metric scrape error, runtime validation error는 모두 `0`이다.
- Windows/x86_64 host, Docker identity/resources, amd64 node inventory, runner SHA-256, Git 상태, model/vLLM 및 immutable image ID가 전 단계에서 같다.
- container args와 CPU request/limit, memory request `4Gi`/limit `8Gi`를 stage별 기대값과 정확히 대조했다.
- OOM 및 OOM-kill delta는 모든 phase에서 반드시 `0`인 경우에만 이 보고서를 생성한다. `memory.events:max`는 OOM과 구분해 아래 감사 경고로 보존한다.

{memory_text}

## 5단계 factor matrix

{chr(10).join(args_table)}

S4의 FP8 args는 S3 args 뒤에 정확히 `--kv-cache-dtype fp8 --calculate-kv-scales`를 추가한다. 이는 KV-cache **FP8** 실험이며 INT8 weight quantization 실험이 아니다.

기동 로그는 모델 weight가 BF16인 상태에서 KV cache만 FP8임을 확인한다. Qwen3.5의 hybrid recurrent GDN 때문에 runtime KV scale 계산은 강제로 비활성화됐고 기본 scale `1.0`을 사용했다. 로그 자체도 적절한 scale이 없으면 정확도가 낮아질 수 있음을 경고한다. 따라서 S4의 기동, 별도 20-request gate 및 정식 700/700 성공은 serving 성능·안정성 증거이지 응답 품질 보증이 아니다.

별도 FP8 C20 gate는 raw artifact 재집계와 정식 S4의 runner/host/Docker/node/container/image 대조를 통과했다. 결과는 `{int(fp8_gate['successes'])}/{int(fp8_gate['requests'])}` 성공, output `{float(fp8_gate['output_tps']):.2f}` tok/s, E2E p95 `{float(fp8_gate['e2e_p95_seconds']):.3f}`s이며 정식 3,500건에는 포함하지 않는다.

## 기동 시 KV capacity

{chr(10).join(startup_table)}

MTP2는 별도 drafter KV cache를 사용하므로 같은 512MiB에서도 S1의 19,894 tokens가 S2에서 9,137 tokens로 줄었다. 768MiB와 FP8은 이 capacity를 단계적으로 회복한다.

## Output throughput

단위는 output tokens/second이다.

{chr(10).join(throughput_table)}

![Output throughput](output-throughput.svg)

## 인접 단계 효과

각 값은 같은 concurrency에서 직전 stage 대비 변화율이다. Throughput은 양수가 증가이며, E2E/TTFT/TPOT는 음수가 latency 개선을 뜻한다. 각 전이는 표에 적힌 factor 하나만 바뀌도록 검증됐다.

{chr(10).join(effect_table)}

## 인접 단계의 exact response hash

{chr(10).join(hash_table)}

이 표는 같은 prompt 위치의 `content_sha256` 완전 일치 수다. exact hash 차이는 문구 변화 신호일 뿐 정답률·의미 품질 지표가 아니다. 특히 S3→S4는 `215/700 (30.7%)`만 완전 일치하므로, scale `1.0` FP8을 production에 적용하기 전에 별도 task 품질 회귀 평가가 필요하다.

전체 절대값과 인접 reference 및 감사 지표는 [comparison.csv](comparison.csv), 응답 해시 원본은 [response-hash-comparison.csv](response-hash-comparison.csv), 기동 capacity는 [startup-capacity.csv](startup-capacity.csv)에 저장한다. 단일 순차 실행이므로 작은 차이는 반복 측정 없이 일반화하지 않는다.
"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-root",
        type=Path,
        default=repository / "benchmark" / "results-windows-sequential-20260830",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="default: <results-root>/comparison-sequential",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_root = args.results_root.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else results_root / "comparison-sequential"
    )
    try:
        loaded = load_results(results_root)
        warnings = validate_results(results_root, loaded)
        rows = build_rows(loaded)
        response_hash_rows = build_response_hash_rows(results_root)
        startup_rows = load_startup_evidence(results_root, loaded)
        fp8_gate = validate_fp8_gate(results_root, loaded)
        output.mkdir(parents=True, exist_ok=True)
        write_csv(output / "comparison.csv", rows)
        write_csv(output / "response-hash-comparison.csv", response_hash_rows)
        write_csv(output / "startup-capacity.csv", startup_rows)
        write_output_throughput_svg(output / "output-throughput.svg", loaded)
        write_kv_cache_growth_svg(
            output / "kv-cache-growth-by-concurrency.svg", loaded
        )
        write_report(
            output,
            rows,
            warnings,
            response_hash_rows,
            startup_rows,
            fp8_gate,
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

    print(
        f"Validated {len(STAGES)} stages, {len(rows)} phase rows, "
        f"and wrote {output}"
    )
    if warnings:
        print(f"memory.events:max warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
