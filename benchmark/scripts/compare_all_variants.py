#!/usr/bin/env python3
"""Validate and compare every completed CPU serving experiment variant."""

from __future__ import annotations

import argparse
import copy
import csv
import html
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from analyze import aggregate as aggregate_raw


CONCURRENCIES = (1, 2, 5, 10, 20, 50, 100)
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
COLORS = (
    "#1d4ed8",
    "#9333ea",
    "#059669",
    "#e11d48",
    "#ea580c",
    "#0891b2",
    "#4f46e5",
    "#65a30d",
)


class ComparisonError(RuntimeError):
    """Raised when benchmark artifacts cannot form a valid comparison."""


@dataclass(frozen=True)
class VariantSpec:
    name: str
    display_name: str
    cpu_limit: int
    mtp_enabled: bool
    kv_bytes: str
    max_num_seqs: int
    same_cpu_reference: str | None
    direct_effect: str
    legacy_bundle: bool = False

    @property
    def kv_mib(self) -> int:
        return int(self.kv_bytes) // 1024**2


VARIANTS = (
    VariantSpec(
        "baseline",
        "CPU6 baseline",
        6,
        False,
        KV_512_BYTES,
        20,
        None,
        "reference",
    ),
    VariantSpec(
        "baseline-cpu8",
        "CPU8 baseline",
        8,
        False,
        KV_512_BYTES,
        20,
        None,
        "CPU limit 6→8 (reported in CPU6-baseline column)",
    ),
    VariantSpec(
        "mtp",
        "CPU6 MTP2",
        6,
        True,
        KV_512_BYTES,
        20,
        "baseline",
        "MTP2 only",
    ),
    VariantSpec(
        "mtp-cpu8",
        "CPU8 MTP2",
        8,
        True,
        KV_512_BYTES,
        20,
        "baseline-cpu8",
        "MTP2 only",
    ),
    VariantSpec(
        "mtp-kv-tuned",
        "CPU6 MTP2 + legacy capacity bundle",
        6,
        True,
        KV_768_BYTES,
        24,
        "mtp",
        "legacy KV768+maxseq24 bundle (joint effect)",
        legacy_bundle=True,
    ),
    VariantSpec(
        "mtp-kv-tuned-cpu8",
        "CPU8 MTP2 + legacy capacity bundle",
        8,
        True,
        KV_768_BYTES,
        24,
        "mtp-cpu8",
        "legacy KV768+maxseq24 bundle (joint effect)",
        legacy_bundle=True,
    ),
    VariantSpec(
        "mtp-kv768-cpu8",
        "CPU8 MTP2 + KV768 only",
        8,
        True,
        KV_768_BYTES,
        20,
        "mtp-cpu8",
        "KV 512→768MiB only",
    ),
    VariantSpec(
        "mtp-seq24-cpu8",
        "CPU8 MTP2 + maxseq24 only",
        8,
        True,
        KV_512_BYTES,
        24,
        "mtp-cpu8",
        "max-num-seqs 20→24 only",
    ),
)
SPEC_BY_NAME = {spec.name: spec for spec in VARIANTS}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComparisonError(f"{path}:{line_number}: invalid request JSON") from exc
        if not isinstance(value, dict):
            raise ComparisonError(f"{path}:{line_number}: request record is not an object")
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


def percent_change(before: Any, after: Any) -> float:
    before_number = finite(before)
    after_number = finite(after)
    if not math.isfinite(before_number) or before_number == 0:
        return math.nan
    if not math.isfinite(after_number):
        return math.nan
    return 100 * (after_number / before_number - 1)


def fmt(value: Any, digits: int = 6) -> str:
    number = finite(value)
    return "" if not math.isfinite(number) else f"{number:.{digits}f}"


def expected_args(spec: VariantSpec) -> list[str]:
    args = list(BASE_ARGS)
    args[args.index("--max-num-seqs") + 1] = str(spec.max_num_seqs)
    args[args.index("--kv-cache-memory-bytes") + 1] = spec.kv_bytes
    if spec.mtp_enabled:
        args.extend(("--speculative-config", MTP_CONFIG))
    return args


def expected_resources(spec: VariantSpec) -> dict[str, dict[str, str]]:
    return {
        "limits": {"cpu": str(spec.cpu_limit), "memory": "6656Mi"},
        "requests": {"cpu": "4", "memory": "4Gi"},
    }


def normalize_env(entries: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(entries, list):
        raise ComparisonError("container env is not a list")
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict) or "name" not in entry or "value" not in entry:
            raise ComparisonError(f"unsupported container env entry: {entry!r}")
        normalized.append((str(entry["name"]), str(entry["value"])))
    return tuple(normalized)


def normalized_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized.pop("experiment", None)
    return normalized


def model_signature(endpoint: Any) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(endpoint, dict):
        return ()
    result = []
    for item in endpoint.get("data", []):
        if isinstance(item, dict):
            result.append(
                (
                    item.get("id"),
                    item.get("root"),
                    item.get("owned_by"),
                    item.get("max_model_len"),
                )
            )
    return tuple(sorted(result, key=lambda item: repr(item)))


def require_result_files(results_root: Path) -> None:
    missing: list[str] = []
    for spec in VARIANTS:
        directory = results_root / spec.name
        absent = [
            filename
            for filename in ("summary.json", "run-manifest.json")
            if not (directory / filename).is_file()
        ]
        if absent:
            missing.append(f"  - {spec.name}: {', '.join(absent)} under {directory}")
    if missing:
        raise ComparisonError(
            "Missing required benchmark result(s):\n"
            + "\n".join(missing)
            + "\nAll eight 700-request runs must exist before comprehensive comparison."
        )


def load_results(results_root: Path) -> dict[str, tuple[list[dict], dict]]:
    require_result_files(results_root)
    loaded: dict[str, tuple[list[dict], dict]] = {}
    for spec in VARIANTS:
        directory = results_root / spec.name
        summary = read_json(directory / "summary.json")
        manifest = read_json(directory / "run-manifest.json")
        if not isinstance(summary, list) or not isinstance(manifest, dict):
            raise ComparisonError(f"Malformed summary or manifest for {spec.name}")
        recomputed_summary, recomputed_manifest = aggregate_raw(directory)
        if recomputed_manifest != manifest:
            raise ComparisonError(f"{spec.name}: raw aggregator read a different manifest")
        if comparable(summary) != comparable(recomputed_summary):
            raise ComparisonError(
                f"{spec.name}: summary.json is stale or differs from raw request/metric artifacts; "
                f"rerun analyze.py for {directory}"
            )
        loaded[spec.name] = (
            sorted(summary, key=lambda row: int(row["concurrency"])),
            manifest,
        )
    return loaded


def validate_container(spec: VariantSpec, manifest: dict[str, Any]) -> None:
    kubernetes = manifest.get("environment", {}).get("kubernetes", {})
    container = kubernetes.get("container")
    if not isinstance(container, dict):
        raise ComparisonError(f"{spec.name}: missing captured Kubernetes container spec")
    if container.get("image") != IMAGE:
        raise ComparisonError(
            f"{spec.name}: expected image {IMAGE!r}, found {container.get('image')!r}"
        )
    if container.get("args") != expected_args(spec):
        raise ComparisonError(
            f"{spec.name}: container args do not match exact expected factor settings; "
            f"expected={expected_args(spec)!r}, found={container.get('args')!r}"
        )
    if container.get("resources") != expected_resources(spec):
        raise ComparisonError(
            f"{spec.name}: resources do not match exact expected CPU/memory settings; "
            f"expected={expected_resources(spec)!r}, found={container.get('resources')!r}"
        )
    if normalize_env(container.get("env")) != EXPECTED_ENV:
        raise ComparisonError(
            f"{spec.name}: environment differs from the fixed serving environment"
        )
    captured_variant = kubernetes.get("serving_variant")
    if captured_variant is not None and captured_variant != spec.name:
        raise ComparisonError(
            f"{spec.name}: manifest captured serving-variant={captured_variant!r}"
        )


def validate_results(
    results_root: Path, loaded: dict[str, tuple[list[dict], dict]]
) -> list[int]:
    baseline_rows, baseline_manifest = loaded["baseline"]
    baseline_config = normalized_config(baseline_manifest.get("config", {}))
    baseline_prompt_hash = baseline_manifest.get("prompts_sha256")
    baseline_input_tokens = baseline_manifest.get("input_token_validation")
    baseline_server_version = baseline_manifest.get("server_version")
    baseline_model = model_signature(baseline_manifest.get("model_endpoint"))
    baseline_pods = (
        baseline_manifest.get("environment", {}).get("kubernetes", {}).get("pods")
    )
    if not isinstance(baseline_pods, list) or len(baseline_pods) != 1:
        raise ComparisonError("baseline: expected exactly one captured Kubernetes Pod")
    baseline_image_id = baseline_pods[0].get("image_id")
    if not baseline_image_id:
        raise ComparisonError("baseline: captured Pod image ID is missing")
    if not baseline_prompt_hash or not baseline_input_tokens or not baseline_model:
        raise ComparisonError(
            "baseline: manifest lacks prompt hash, input-token validation, or model identity"
        )
    baseline_tokens = {
        int(row["concurrency"]): (
            int(finite(row["total_prompt_tokens"])),
            int(finite(row["total_completion_tokens"])),
        )
        for row in baseline_rows
    }
    baseline_request_signatures: dict[int, tuple[tuple[Any, ...], ...]] = {}

    for spec in VARIANTS:
        rows, manifest = loaded[spec.name]
        if manifest.get("status") != "completed":
            raise ComparisonError(
                f"{spec.name}: run status is {manifest.get('status')!r}, expected 'completed'"
            )
        endpoint_binding = manifest.get("endpoint_binding")
        if endpoint_binding not in (None, "local-kubernetes-service"):
            raise ComparisonError(
                f"{spec.name}: formal comparison requires the local Kubernetes Service, "
                f"found endpoint_binding={endpoint_binding!r}"
            )
        if endpoint_binding is None and not str(manifest.get("base_url", "")).startswith(
            "http://127.0.0.1:"
        ):
            raise ComparisonError(
                f"{spec.name}: legacy manifest lacks local port-forward evidence"
            )
        config = manifest.get("config", {})
        if config.get("experiment") != spec.name:
            raise ComparisonError(
                f"{spec.name}: manifest config experiment is {config.get('experiment')!r}"
            )
        if normalized_config(config) != baseline_config:
            raise ComparisonError(
                f"{spec.name}: workload config differs by more than experiment name"
            )
        if manifest.get("prompts_sha256") != baseline_prompt_hash:
            raise ComparisonError(f"{spec.name}: prompt workload SHA-256 differs")
        if manifest.get("prompt_count") != 100:
            raise ComparisonError(
                f"{spec.name}: prompt_count={manifest.get('prompt_count')!r}, expected 100"
            )
        if manifest.get("input_token_validation") != baseline_input_tokens:
            raise ComparisonError(f"{spec.name}: tokenized input workload differs")
        if manifest.get("server_version") != baseline_server_version:
            raise ComparisonError(f"{spec.name}: vLLM server version differs")
        if model_signature(manifest.get("model_endpoint")) != baseline_model:
            raise ComparisonError(f"{spec.name}: served model identity or context differs")
        validate_container(spec, manifest)
        pods = manifest.get("environment", {}).get("kubernetes", {}).get("pods")
        if not isinstance(pods, list) or len(pods) != 1:
            raise ComparisonError(f"{spec.name}: expected exactly one captured Kubernetes Pod")
        pod = pods[0]
        if int(pod.get("restart_count", -1)) != 0:
            raise ComparisonError(f"{spec.name}: captured Pod restart count is not zero")
        if pod.get("image_id") != baseline_image_id:
            raise ComparisonError(
                f"{spec.name}: captured Pod image ID differs from baseline"
            )

        row_concurrencies = [int(row["concurrency"]) for row in rows]
        if row_concurrencies != list(CONCURRENCIES):
            raise ComparisonError(
                f"{spec.name}: concurrency rows {row_concurrencies}, expected {list(CONCURRENCIES)}"
            )
        if manifest.get("concurrencies") != list(CONCURRENCIES):
            raise ComparisonError(f"{spec.name}: manifest concurrency matrix differs")
        if len(manifest.get("phases", [])) != len(CONCURRENCIES):
            raise ComparisonError(f"{spec.name}: expected seven completed phases")
        phases = {
            int(phase["concurrency"]): phase for phase in manifest.get("phases", [])
        }
        if sorted(phases) != list(CONCURRENCIES):
            raise ComparisonError(f"{spec.name}: manifest phase matrix differs")

        total_requests = 0
        for row in rows:
            concurrency = int(row["concurrency"])
            requests = int(row["requests"])
            successes = int(row["successes"])
            failures = int(row["failures"])
            total_requests += requests
            if (requests, successes, failures) != (100, 100, 0):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: expected requests/success/failure "
                    f"100/100/0, found {requests}/{successes}/{failures}"
                )
            token_totals = (
                int(finite(row["total_prompt_tokens"])),
                int(finite(row["total_completion_tokens"])),
            )
            if token_totals != baseline_tokens[concurrency]:
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: client token totals differ from baseline"
                )
            if token_totals[0] != int(finite(row["server_prompt_tokens_delta"])):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: client/server prompt token mismatch"
                )
            if token_totals[1] != int(finite(row["server_generation_tokens_delta"])):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: client/server generation token mismatch"
                )
            oom_kills = finite(row.get("oom_kill_events_delta"))
            if not math.isfinite(oom_kills) or oom_kills != 0:
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: invalid OOM-kill delta {oom_kills!r}"
                )

            phase = phases[concurrency]
            if (
                int(phase.get("request_count", -1)),
                int(phase.get("success_count", -1)),
                int(phase.get("failure_count", -1)),
            ) != (100, 100, 0):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: phase metadata is not 100/100/0"
                )
            if phase.get("metrics_scrape_errors"):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: metric scrape errors are present"
                )
            if phase.get("runtime_validation_errors"):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: Pod runtime validation errors are present"
                )
            try:
                wall_seconds = (
                    datetime.fromisoformat(phase["finished_at_utc"])
                    - datetime.fromisoformat(phase["started_at_utc"])
                ).total_seconds()
            except (KeyError, TypeError, ValueError) as exc:
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: invalid phase timestamps"
                ) from exc
            duration = finite(phase.get("duration_seconds"))
            timer_gap = abs(wall_seconds - duration)
            if not math.isfinite(duration) or timer_gap > max(5.0, duration * 0.01):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: wall/monotonic timer gap "
                    f"{timer_gap:.2f}s exceeds tolerance"
                )
            for file_key in ("requests_file", "metrics_file"):
                artifact = results_root / spec.name / phase.get(file_key, "")
                if not artifact.is_file():
                    raise ComparisonError(
                        f"{spec.name} C={concurrency}: missing phase artifact {artifact}"
                    )
            request_artifact = (
                results_root / spec.name / phase["requests_file"]
            )
            request_rows = read_jsonl(request_artifact)
            if len(request_rows) != 100 or any(
                request.get("status") != "success" for request in request_rows
            ):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: raw request file is not 100/100 successful"
                )
            request_signature = tuple(
                (
                    int(request["sequence"]),
                    request["prompt_id"],
                    int(request["prompt_tokens"]),
                    int(request["completion_tokens"]),
                )
                for request in request_rows
            )
            if spec.name == "baseline":
                baseline_request_signatures[concurrency] = request_signature
            elif request_signature != baseline_request_signatures[concurrency]:
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: raw prompt order or token work differs "
                    "from baseline"
                )
        if total_requests != 700:
            raise ComparisonError(
                f"{spec.name}: expected exactly 700 measured requests, found {total_requests}"
            )
    return list(CONCURRENCIES)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_comparison_rows(
    loaded: dict[str, tuple[list[dict], dict]], concurrencies: list[int]
) -> list[dict[str, Any]]:
    by_variant = {
        name: {int(row["concurrency"]): row for row in rows}
        for name, (rows, _manifest) in loaded.items()
    }
    output: list[dict[str, Any]] = []
    for concurrency in concurrencies:
        cpu6_baseline = by_variant["baseline"][concurrency]
        for spec in VARIANTS:
            current = by_variant[spec.name][concurrency]
            reference = (
                by_variant[spec.same_cpu_reference][concurrency]
                if spec.same_cpu_reference
                else None
            )
            output.append(
                {
                    "concurrency": concurrency,
                    "variant": spec.name,
                    "display_name": spec.display_name,
                    "cpu_limit": spec.cpu_limit,
                    "mtp_enabled": str(spec.mtp_enabled).lower(),
                    "kv_cache_mib": spec.kv_mib,
                    "max_num_seqs": spec.max_num_seqs,
                    "legacy_bundle": str(spec.legacy_bundle).lower(),
                    "requests": int(current["requests"]),
                    "output_tps": fmt(current["output_token_throughput_tps"]),
                    "cpu6_baseline_output_tps": fmt(
                        cpu6_baseline["output_token_throughput_tps"]
                    ),
                    "vs_cpu6_baseline_output_percent": fmt(
                        percent_change(
                            cpu6_baseline["output_token_throughput_tps"],
                            current["output_token_throughput_tps"],
                        )
                    ),
                    "same_cpu_reference": spec.same_cpu_reference or "",
                    "direct_effect": spec.direct_effect,
                    "same_cpu_reference_output_tps": (
                        fmt(reference["output_token_throughput_tps"])
                        if reference
                        else ""
                    ),
                    "same_cpu_direct_output_percent": (
                        fmt(
                            percent_change(
                                reference["output_token_throughput_tps"],
                                current["output_token_throughput_tps"],
                            )
                        )
                        if reference
                        else ""
                    ),
                    "e2e_p95_seconds": fmt(current["e2e_seconds_p95"]),
                    "ttft_p95_seconds": fmt(current["ttft_seconds_p95"]),
                    "tpot_p95_ms": fmt(current["tpot_ms_p95"]),
                    "peak_running": fmt(current["peak_running_requests"], 0),
                    "peak_waiting": fmt(current["peak_waiting_requests"], 0),
                    "peak_kv_percent": fmt(current["peak_kv_cache_percent"]),
                    "avg_cpu_cores": fmt(current["avg_pod_cpu_cores"]),
                    "peak_memory_gib": fmt(current["peak_pod_memory_gib"]),
                }
            )
    return output


def chart_bounds(values: list[float]) -> tuple[float, float]:
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        return 0.0, 1.0
    low = min(0.0, min(finite_values))
    high = max(0.0, max(finite_values))
    span = high - low
    if span == 0:
        span = max(1.0, abs(high) * 0.2)
    return low - span * 0.08, high + span * 0.08


def line_chart(
    path: Path,
    title: str,
    y_label: str,
    concurrencies: list[int],
    series: list[tuple[str, list[float]]],
) -> None:
    width = 1180
    legend_columns = 2
    legend_rows = math.ceil(len(series) / legend_columns)
    top = 70 + legend_rows * 25
    height = top + 460
    left, right, bottom = 100, 45, 75
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = [value for _label, points in series for value in points]
    y_min, y_max = chart_bounds(values)

    def x_position(index: int) -> float:
        if len(concurrencies) == 1:
            return left + plot_width / 2
        return left + index / (len(concurrencies) - 1) * plot_width

    def y_position(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_height

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="32" text-anchor="middle" font-size="22" font-family="sans-serif" font-weight="600">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = y_min + (y_max - y_min) * tick / 5
        y = y_position(value)
        stroke = "#9ca3af" if abs(value) < (y_max - y_min) / 1000 else "#e5e7eb"
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}" stroke="{stroke}"/>'
        )
        parts.append(
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="12" font-family="sans-serif" fill="#4b5563">{value:.1f}</text>'
        )
    for index, concurrency in enumerate(concurrencies):
        x = x_position(index)
        parts.append(
            f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_height}" stroke="#f3f4f6"/>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{top + plot_height + 25}" text-anchor="middle" font-size="13" font-family="sans-serif">{concurrency}</text>'
        )
    parts.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#111827"/>',
            f'<text x="{left + plot_width / 2}" y="{height - 20}" text-anchor="middle" font-size="14" font-family="sans-serif">Concurrency</text>',
            f'<text transform="translate(25 {top + plot_height / 2}) rotate(-90)" text-anchor="middle" font-size="14" font-family="sans-serif">{html.escape(y_label)}</text>',
        )
    )

    legend_width = 540
    for series_index, (label, points) in enumerate(series):
        color = COLORS[series_index % len(COLORS)]
        column = series_index % legend_columns
        row = series_index // legend_columns
        legend_x = left + column * legend_width
        legend_y = 58 + row * 25
        parts.append(
            f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{legend_x + 31}" y="{legend_y + 4}" font-size="12" font-family="sans-serif">{html.escape(label)}</text>'
        )
        point_pairs = [
            (x_position(index), y_position(value))
            for index, value in enumerate(points)
            if math.isfinite(value)
        ]
        if point_pairs:
            coordinates = " ".join(f"{x:.2f},{y:.2f}" for x, y in point_pairs)
            parts.append(
                f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="2.5"/>'
            )
            for x, y in point_pairs:
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="{color}"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def kv_cache_tradeoff_chart(
    path: Path,
    by_variant: dict[str, dict[int, dict[str, Any]]],
    concurrency: int = 20,
) -> None:
    """Show the controlled KV-byte-budget trade-off without mixing metric units."""
    reference_spec = SPEC_BY_NAME["mtp-cpu8"]
    tuned_spec = SPEC_BY_NAME["mtp-kv768-cpu8"]
    reference = by_variant[reference_spec.name][concurrency]
    tuned = by_variant[tuned_spec.name][concurrency]

    running_before = finite(reference["peak_running_requests"])
    running_after = finite(tuned["peak_running_requests"])
    waiting_before = finite(reference["peak_waiting_requests"])
    waiting_after = finite(tuned["peak_waiting_requests"])
    scheduler_values = (
        running_before,
        running_after,
        waiting_before,
        waiting_after,
    )
    if any(not math.isfinite(value) or value < 0 for value in scheduler_values):
        raise ComparisonError(
            f"KV trade-off C={concurrency}: scheduler peaks must be finite and nonnegative"
        )
    performance_metrics = (
        (
            "Output throughput",
            "tok/s",
            finite(reference["output_token_throughput_tps"]),
            finite(tuned["output_token_throughput_tps"]),
            False,
        ),
        (
            "TPOT p95",
            "ms/token",
            finite(reference["tpot_ms_p95"]),
            finite(tuned["tpot_ms_p95"]),
            True,
        ),
        (
            "E2E p95",
            "seconds",
            finite(reference["e2e_seconds_p95"]),
            finite(tuned["e2e_seconds_p95"]),
            True,
        ),
    )
    throughput_delta = percent_change(
        performance_metrics[0][2], performance_metrics[0][3]
    )
    tpot_delta = percent_change(performance_metrics[1][2], performance_metrics[1][3])
    e2e_delta = percent_change(performance_metrics[2][2], performance_metrics[2][3])
    metric_values = [
        value
        for _label, _unit, before, after, _lower_is_better in performance_metrics
        for value in (before, after)
    ]
    if any(not math.isfinite(value) or value <= 0 for value in metric_values):
        raise ComparisonError(
            f"KV trade-off C={concurrency}: performance values must be finite and positive"
        )
    accessibility_description = (
        f"With CPU8, MTP2 and max-num-seqs 20 fixed, increasing the KV cache "
        f"from {reference_spec.kv_mib} to {tuned_spec.kv_mib} MiB changed peak "
        f"running requests from {running_before:.0f} to {running_after:.0f} and "
        f"peak waiting requests from {waiting_before:.0f} to "
        f"{waiting_after:.0f}. Output throughput changed {throughput_delta:+.1f} "
        f"percent, TPOT p95 changed {tpot_delta:+.1f} percent, and E2E p95 changed "
        f"{e2e_delta:+.1f} percent. Running and waiting are independently sampled "
        "peaks."
    )

    width, height = 1280, 720
    before_color = "#2563eb"
    after_color = "#7c3aed"
    running_color = "#059669"
    waiting_color = "#ea580c"
    neutral = "#4b5563"
    border = "#d1d5db"
    grid = "#e5e7eb"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="kv-title kv-desc">',
        f'<title id="kv-title">KV cache byte-budget trade-off at concurrency {concurrency}</title>',
        f'<desc id="kv-desc">{html.escape(accessibility_description)}</desc>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#6b7280"/></marker></defs>',
        '<text x="640" y="38" text-anchor="middle" font-size="24" font-family="sans-serif" font-weight="600">KV cache 증량의 capacity–performance trade-off</text>',
        f'<text x="640" y="64" text-anchor="middle" font-size="15" font-family="sans-serif" fill="#4b5563">Controlled A/B: CPU 8 · MTP2 · max-num-seqs 20 고정 · concurrency {concurrency}</text>',
    ]

    panels = ((45, 92, 330, 485), (420, 92, 350, 485), (815, 92, 420, 485))
    for x, y, panel_width, panel_height in panels:
        parts.append(
            f'<rect x="{x}" y="{y}" width="{panel_width}" height="{panel_height}" fill="none" stroke="{border}"/>'
        )

    # 1) Changed input: KV byte budget only.
    parts.extend(
        (
            '<text x="67" y="124" font-size="18" font-family="sans-serif" font-weight="600">1. 변경한 값: KV byte budget</text>',
            '<text x="67" y="153" font-size="15" font-family="sans-serif" fill="#4b5563">KV512 (reference)</text>',
            f'<rect x="67" y="165" width="{220 * reference_spec.kv_mib / tuned_spec.kv_mib:.1f}" height="35" fill="{before_color}"/>',
            f'<text x="{75 + 220 * reference_spec.kv_mib / tuned_spec.kv_mib:.1f}" y="188" font-size="15" font-family="sans-serif" fill="#111827">{reference_spec.kv_mib} MiB</text>',
            '<text x="67" y="233" font-size="15" font-family="sans-serif" fill="#4b5563">KV768 (increased)</text>',
            f'<rect x="67" y="245" width="220" height="35" fill="{after_color}"/>',
            f'<text x="295" y="268" font-size="15" font-family="sans-serif" fill="#111827">{tuned_spec.kv_mib} MiB</text>',
            f'<text x="67" y="322" font-size="22" font-family="sans-serif" font-weight="600" fill="{after_color}">+{percent_change(reference_spec.kv_mib, tuned_spec.kv_mib):.0f}% bytes</text>',
            '<line x1="67" y1="345" x2="353" y2="345" stroke="#e5e7eb"/>',
            '<text x="67" y="378" font-size="15" font-family="sans-serif" fill="#111827">고정 조건</text>',
            '<text x="67" y="405" font-size="15" font-family="sans-serif" fill="#4b5563">• model / BF16 weights</text>',
            '<text x="67" y="430" font-size="15" font-family="sans-serif" fill="#4b5563">• CPU limit 8 · MTP2</text>',
            '<text x="67" y="455" font-size="15" font-family="sans-serif" fill="#4b5563">• max-num-seqs 20</text>',
            '<text x="67" y="480" font-size="15" font-family="sans-serif" fill="#4b5563">• 동일 100 prompts / 출력 tokens</text>',
        )
    )

    # 2) Scheduler observations. Running and waiting use separate bars because
    # their sampled peaks need not occur at the same instant.
    scheduler_width = 210
    scheduler_max = max(*scheduler_values, 1.0)
    parts.extend(
        (
            '<text x="442" y="124" font-size="18" font-family="sans-serif" font-weight="600">2. 관찰: scheduler peak 변화</text>',
            f'<text x="442" y="164" font-size="15" font-family="sans-serif" font-weight="600" fill="{running_color}">Peak running requests</text>',
            '<text x="442" y="196" font-size="14" font-family="sans-serif" fill="#4b5563">512</text>',
            f'<rect x="482" y="181" width="{scheduler_width * running_before / scheduler_max:.1f}" height="21" fill="{running_color}"/>',
            f'<text x="{490 + scheduler_width * running_before / scheduler_max:.1f}" y="197" font-size="14" font-family="sans-serif">{running_before:.0f}</text>',
            '<text x="442" y="230" font-size="14" font-family="sans-serif" fill="#4b5563">768</text>',
            f'<rect x="482" y="215" width="{scheduler_width * running_after / scheduler_max:.1f}" height="21" fill="{running_color}"/>',
            f'<text x="{490 + scheduler_width * running_after / scheduler_max:.1f}" y="231" font-size="14" font-family="sans-serif">{running_after:.0f}</text>',
            f'<text x="442" y="280" font-size="15" font-family="sans-serif" font-weight="600" fill="{waiting_color}">Peak waiting requests</text>',
            '<text x="442" y="312" font-size="14" font-family="sans-serif" fill="#4b5563">512</text>',
            f'<rect x="482" y="297" width="{scheduler_width * waiting_before / scheduler_max:.1f}" height="21" fill="{waiting_color}"/>',
            f'<text x="{490 + scheduler_width * waiting_before / scheduler_max:.1f}" y="313" font-size="14" font-family="sans-serif">{waiting_before:.0f}</text>',
            '<text x="442" y="346" font-size="14" font-family="sans-serif" fill="#4b5563">768</text>',
            f'<rect x="482" y="331" width="{scheduler_width * waiting_after / scheduler_max:.1f}" height="21" fill="{waiting_color}"/>',
            f'<text x="{490 + scheduler_width * waiting_after / scheduler_max:.1f}" y="347" font-size="14" font-family="sans-serif">{waiting_after:.0f}</text>',
            f'<text x="442" y="400" font-size="20" font-family="sans-serif" font-weight="600" fill="{running_color}">running {running_before:.0f} → {running_after:.0f}</text>',
            f'<text x="442" y="431" font-size="20" font-family="sans-serif" font-weight="600" fill="{waiting_color}">waiting {waiting_before:.0f} → {waiting_after:.0f}</text>',
            '<text x="442" y="480" font-size="14" font-family="sans-serif" fill="#4b5563">※ run/wait는 1초 metric의 독립 peak</text>',
            '<text x="442" y="503" font-size="14" font-family="sans-serif" fill="#4b5563">값이며 같은 시점의 합이 아니다.</text>',
        )
    )

    # 3) Performance small multiples: every metric gets its own scale.
    parts.extend(
        (
            '<text x="837" y="124" font-size="18" font-family="sans-serif" font-weight="600">3. 관찰: 성능 지표 변화</text>',
            f'<rect x="837" y="141" width="13" height="13" fill="{before_color}"/><text x="858" y="153" font-size="14" font-family="sans-serif" fill="{neutral}">KV512</text>',
            f'<rect x="925" y="141" width="13" height="13" fill="{after_color}"/><text x="946" y="153" font-size="14" font-family="sans-serif" fill="{neutral}">KV768</text>',
        )
    )
    metric_top = 190
    metric_gap = 122
    bar_x = 875
    bar_width = 245
    for index, (label, unit, before, after, lower_is_better) in enumerate(
        performance_metrics
    ):
        y = metric_top + index * metric_gap
        maximum = max(before, after) * 1.08
        before_width = bar_width * before / maximum
        after_width = bar_width * after / maximum
        delta = percent_change(before, after)
        improving = delta < 0 if lower_is_better else delta > 0
        if abs(delta) < 0.05:
            delta_color = neutral
        else:
            delta_color = "#059669" if improving else "#b91c1c"
        parts.extend(
            (
                f'<text x="837" y="{y}" font-size="15" font-family="sans-serif" font-weight="600">{html.escape(label)} <tspan fill="{neutral}" font-weight="400">({html.escape(unit)})</tspan></text>',
                f'<text x="1211" y="{y}" text-anchor="end" font-size="15" font-family="sans-serif" font-weight="600" fill="{delta_color}">{delta:+.1f}%</text>',
                f'<line x1="{bar_x}" y1="{y + 28}" x2="{bar_x + bar_width}" y2="{y + 28}" stroke="{grid}"/>',
                f'<text x="837" y="{y + 34}" font-size="14" font-family="sans-serif" fill="{neutral}">512</text>',
                f'<rect x="{bar_x}" y="{y + 17}" width="{before_width:.1f}" height="18" fill="{before_color}"/>',
                f'<text x="{bar_x + before_width + 7:.1f}" y="{y + 31}" font-size="14" font-family="sans-serif" fill="#111827">{before:.2f}</text>',
                f'<line x1="{bar_x}" y1="{y + 57}" x2="{bar_x + bar_width}" y2="{y + 57}" stroke="{grid}"/>',
                f'<text x="837" y="{y + 63}" font-size="14" font-family="sans-serif" fill="{neutral}">768</text>',
                f'<rect x="{bar_x}" y="{y + 46}" width="{after_width:.1f}" height="18" fill="{after_color}"/>',
                f'<text x="{bar_x + after_width + 7:.1f}" y="{y + 60}" font-size="14" font-family="sans-serif" fill="#111827">{after:.2f}</text>',
            )
        )

    parts.extend(
        (
            '<line x1="375" y1="334" x2="409" y2="334" stroke="#6b7280" stroke-width="2" marker-end="url(#arrow)"/>',
            '<line x1="770" y1="334" x2="804" y2="334" stroke="#6b7280" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arrow)"/>',
            '<text x="640" y="615" text-anchor="middle" font-size="20" font-family="sans-serif" font-weight="600">결론: KV capacity 변화 ≠ per-token speed 가속 보장</text>',
            '<text x="640" y="646" text-anchor="middle" font-size="16" font-family="sans-serif" fill="#374151">같은 CPU8에서 scheduler peak와 throughput·TPOT·E2E가 함께 변했다.</text>',
            '<text x="640" y="673" text-anchor="middle" font-size="15" font-family="sans-serif" fill="#4b5563">KV 이외의 CPU-side 자원 압력과 일치하지만, 정확한 원인은 profiler로 추가 분해해야 한다.</text>',
        )
    )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def kv_cache_growth_chart(
    path: Path,
    by_variant: dict[str, dict[int, dict[str, Any]]],
    concurrencies: list[int],
) -> None:
    """Plot concurrency-driven KV block occupancy in percent and MiB-equivalent."""
    if tuple(concurrencies) != CONCURRENCIES:
        raise ComparisonError(
            "KV growth chart requires the canonical measured concurrency matrix"
        )

    reference_spec = SPEC_BY_NAME["mtp-cpu8"]
    increased_spec = SPEC_BY_NAME["mtp-kv768-cpu8"]
    fixed_reference = (
        reference_spec.cpu_limit,
        reference_spec.mtp_enabled,
        reference_spec.max_num_seqs,
    )
    fixed_increased = (
        increased_spec.cpu_limit,
        increased_spec.mtp_enabled,
        increased_spec.max_num_seqs,
    )
    if fixed_reference != fixed_increased or fixed_reference != (8, True, 20):
        raise ComparisonError(
            "KV growth chart variants must hold CPU8, MTP2 and max-num-seqs=20 fixed"
        )
    if (reference_spec.kv_mib, increased_spec.kv_mib) != (512, 768):
        raise ComparisonError(
            "KV growth chart requires the controlled 512MiB and 768MiB budgets"
        )

    colors = ("#2563eb", "#7c3aed")
    series: list[dict[str, Any]] = []
    for spec, color, marker in (
        (reference_spec, colors[0], "circle"),
        (increased_spec, colors[1], "square"),
    ):
        percentages: list[float] = []
        used_mib: list[float] = []
        for concurrency in concurrencies:
            try:
                row = by_variant[spec.name][concurrency]
            except KeyError as exc:
                raise ComparisonError(
                    f"{spec.name}: missing C={concurrency} for KV growth chart"
                ) from exc
            percentage = finite(row["peak_kv_cache_percent"])
            if (
                not math.isfinite(percentage)
                or percentage < 0
                or percentage > 100 + 1e-6
            ):
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: peak KV percent must be in [0, 100]"
                )
            percentage = min(percentage, 100.0)
            estimated_mib = spec.kv_mib * percentage / 100
            if estimated_mib < 0 or estimated_mib > spec.kv_mib + 1e-6:
                raise ComparisonError(
                    f"{spec.name} C={concurrency}: invalid estimated occupied KV MiB"
                )
            percentages.append(percentage)
            used_mib.append(estimated_mib)
        series.append(
            {
                "label": f"KV budget {spec.kv_mib}MiB",
                "spec": spec,
                "color": color,
                "marker": marker,
                "dash": "" if spec is reference_spec else "5 4",
                "percentages": percentages,
                "used_mib": used_mib,
            }
        )

    def plateau_start(values: list[float]) -> int | None:
        tolerance = max(1e-6, max(abs(value) for value in values) * 1e-6)
        for index in range(len(values) - 1):
            suffix = values[index:]
            if max(suffix) - min(suffix) <= tolerance:
                return concurrencies[index]
        return None

    def plateau_label(value: int | None) -> str:
        return f"C={value}" if value is not None else "not observed"

    def plateau_korean(label: str, value: int | None) -> str:
        return (
            f"{label} C={value}부터"
            if value is not None
            else f"{label} plateau 미관찰"
        )

    plateau_512 = plateau_start(series[0]["used_mib"])
    plateau_768 = plateau_start(series[1]["used_mib"])
    plateau_count = sum(value is not None for value in (plateau_512, plateau_768))
    if plateau_count == 2:
        plateau_note = (
            "plateau로 판정된 구간에서는 concurrency가 증가해도 sampled peak "
            "KV occupancy가 더 증가하지 않았다."
        )
    elif plateau_count == 1:
        plateau_note = (
            "plateau로 판정된 series만 이후 sampled peak KV occupancy가 "
            "평탄했으며, 다른 series는 plateau가 관찰되지 않았다."
        )
    else:
        plateau_note = (
            "마지막 두 측정점까지 평탄한 suffix가 없어 plateau로 판정하지 않았다."
        )
    series_descriptions = []
    for item in series:
        observations = ", ".join(
            f"C{concurrency} {used:.1f} MiB ({percentage:.1f} percent)"
            for concurrency, used, percentage in zip(
                concurrencies,
                item["used_mib"],
                item["percentages"],
            )
        )
        series_descriptions.append(f"{item['label']}: {observations}")
    description = (
        "CPU8 MTP2 max-num-seqs 20. "
        + "; ".join(series_descriptions)
        + ". Observed plateau starts: KV budget 512MiB "
        + plateau_label(plateau_512)
        + ", KV budget 768MiB "
        + plateau_label(plateau_768)
        + ". "
        "MiB values are configured budget multiplied by the one-second sampled "
        "used-block fraction, not RSS."
    )

    width, height = 1280, 890
    left, right = 120, 70
    plot_width = width - left - right
    top_plot_top, top_plot_bottom = 135, 430
    lower_plot_top, lower_plot_bottom = 550, 760
    neutral, grid, border = "#4b5563", "#e5e7eb", "#9ca3af"

    def x_position(index: int) -> float:
        return left + index / (len(concurrencies) - 1) * plot_width

    def y_top(value: float) -> float:
        return top_plot_bottom - value / 800 * (top_plot_bottom - top_plot_top)

    def y_lower(value: float) -> float:
        return lower_plot_bottom - value / 100 * (
            lower_plot_bottom - lower_plot_top
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="kv-growth-title kv-growth-desc">',
        '<title id="kv-growth-title">Concurrency versus peak KV cache occupancy</title>',
        f'<desc id="kv-growth-desc">{html.escape(description)}</desc>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        '<text x="640" y="38" text-anchor="middle" font-size="24" font-family="sans-serif" font-weight="600">동시성 증가에 따른 peak KV cache 점유</text>',
        '<text x="640" y="66" text-anchor="middle" font-size="15" font-family="sans-serif" fill="#4b5563">Controlled A/B: CPU 8 · MTP2 · max-num-seqs 20 · 동일 100 prompts</text>',
    ]

    for index, item in enumerate(series):
        legend_x = 375 + index * 290
        color = item["color"]
        dash = (
            f' stroke-dasharray="{item["dash"]}"'
            if item["dash"]
            else ""
        )
        parts.append(
            f'<line x1="{legend_x}" y1="98" x2="{legend_x + 34}" y2="98" stroke="{color}" stroke-width="3"{dash}/>'
        )
        if item["marker"] == "circle":
            parts.append(
                f'<circle cx="{legend_x + 17}" cy="98" r="5" fill="{color}"/>'
            )
        else:
            parts.append(
                f'<rect x="{legend_x + 12}" y="93" width="10" height="10" fill="{color}"/>'
            )
        parts.append(
            f'<text x="{legend_x + 44}" y="103" font-size="15" font-family="sans-serif">{html.escape(item["label"])}</text>'
        )

    # Top panel: configured-budget-equivalent occupied capacity.
    parts.extend(
        (
            '<text x="120" y="125" font-size="17" font-family="sans-serif" font-weight="600">A. Peak occupied KV block capacity (MiB-equivalent)</text>',
            f'<rect x="{left}" y="{top_plot_top}" width="{plot_width}" height="{top_plot_bottom - top_plot_top}" fill="none" stroke="{border}"/>',
        )
    )
    for tick in (0, 200, 400, 600, 800):
        y = y_top(tick)
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="{grid}"/>',
                f'<text x="{left - 14}" y="{y + 5:.1f}" text-anchor="end" font-size="14" font-family="sans-serif" fill="{neutral}">{tick}</text>',
            )
        )
    parts.append(
        f'<text transform="translate(28 {(top_plot_top + top_plot_bottom) / 2}) rotate(-90)" text-anchor="middle" font-size="15" font-family="sans-serif">Estimated occupied budget (MiB)</text>'
    )
    for item in series:
        budget = item["spec"].kv_mib
        y = y_top(budget)
        color = item["color"]
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="{color}" stroke-width="1.5" stroke-dasharray="7 5" opacity="0.65"/>',
                f'<text x="{left + plot_width - 8}" y="{y - 7:.1f}" text-anchor="end" font-size="13" font-family="sans-serif" fill="{color}">{budget}MiB configured ceiling</text>',
            )
        )
    for item in series:
        color = item["color"]
        values = item["used_mib"]
        dash = (
            f' stroke-dasharray="{item["dash"]}"'
            if item["dash"]
            else ""
        )
        coordinates = " ".join(
            f"{x_position(index):.1f},{y_top(value):.1f}"
            for index, value in enumerate(values)
        )
        parts.append(
            f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3"{dash}/>'
        )
        for index, value in enumerate(values):
            x, y = x_position(index), y_top(value)
            if item["marker"] == "circle":
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
            else:
                parts.append(
                    f'<rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" fill="{color}"/>'
                )
    c5_index = concurrencies.index(5)
    c10_index = concurrencies.index(10)
    parts.extend(
        (
            f'<text x="{x_position(c5_index) - 12:.1f}" y="{y_top(series[0]["used_mib"][c5_index]) - 20:.1f}" text-anchor="end" font-size="14" font-family="sans-serif" fill="{series[0]["color"]}">{series[0]["used_mib"][c5_index]:.1f}MiB · {series[0]["percentages"][c5_index]:.1f}%</text>',
            f'<text x="{x_position(c5_index) + 12:.1f}" y="{y_top(series[1]["used_mib"][c5_index]) + 28:.1f}" text-anchor="start" font-size="14" font-family="sans-serif" fill="{series[1]["color"]}">{series[1]["used_mib"][c5_index]:.1f}MiB · {series[1]["percentages"][c5_index]:.1f}%</text>',
            f'<text x="{x_position(c10_index) + 12:.1f}" y="{y_top(series[1]["used_mib"][c10_index]) + 27:.1f}" text-anchor="start" font-size="14" font-family="sans-serif" fill="{series[1]["color"]}">{series[1]["used_mib"][c10_index]:.1f}MiB · {series[1]["percentages"][c10_index]:.1f}%</text>',
            f'<text x="640" y="470" text-anchor="middle" font-size="16" font-family="sans-serif" font-weight="600">관찰된 plateau: {plateau_korean("KV512", plateau_512)} · {plateau_korean("KV768", plateau_768)}</text>',
            f'<text x="640" y="497" text-anchor="middle" font-size="14" font-family="sans-serif" fill="#4b5563">{html.escape(plateau_note)}</text>',
        )
    )

    # Lower panel: the raw vLLM used-block fraction for each pool.
    parts.extend(
        (
            '<text x="120" y="540" font-size="17" font-family="sans-serif" font-weight="600">B. Peak used-block ratio within each configured pool</text>',
            f'<rect x="{left}" y="{lower_plot_top}" width="{plot_width}" height="{lower_plot_bottom - lower_plot_top}" fill="none" stroke="{border}"/>',
        )
    )
    for tick in (0, 25, 50, 75, 100):
        y = y_lower(tick)
        parts.extend(
            (
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="{grid}"/>',
                f'<text x="{left - 14}" y="{y + 5:.1f}" text-anchor="end" font-size="14" font-family="sans-serif" fill="{neutral}">{tick}%</text>',
            )
        )
    parts.append(
        f'<text transform="translate(28 {(lower_plot_top + lower_plot_bottom) / 2}) rotate(-90)" text-anchor="middle" font-size="15" font-family="sans-serif">Used KV blocks (%)</text>'
    )
    for item in series:
        color = item["color"]
        values = item["percentages"]
        dash = (
            f' stroke-dasharray="{item["dash"]}"'
            if item["dash"]
            else ""
        )
        coordinates = " ".join(
            f"{x_position(index):.1f},{y_lower(value):.1f}"
            for index, value in enumerate(values)
        )
        parts.append(
            f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3"{dash}/>'
        )
        for index, value in enumerate(values):
            x, y = x_position(index), y_lower(value)
            if item["marker"] == "circle":
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
            else:
                parts.append(
                    f'<rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" fill="{color}"/>'
                )
    for index, concurrency in enumerate(concurrencies):
        x = x_position(index)
        parts.extend(
            (
                f'<line x1="{x:.1f}" y1="{lower_plot_bottom}" x2="{x:.1f}" y2="{lower_plot_bottom + 7}" stroke="#111827"/>',
                f'<text x="{x:.1f}" y="{lower_plot_bottom + 29}" text-anchor="middle" font-size="14" font-family="sans-serif">{concurrency}</text>',
            )
        )
    parts.extend(
        (
            f'<text x="{left + plot_width / 2}" y="{lower_plot_bottom + 58}" text-anchor="middle" font-size="15" font-family="sans-serif">Configured client concurrency (100 requests total)</text>',
            '<text x="640" y="865" text-anchor="middle" font-size="14" font-family="sans-serif" fill="#4b5563">MiB-equivalent = configured KV budget × vLLM used-block fraction; actual RSS가 아님 · 1초 sampled peak · 선은 측정점 연결</text>',
        )
    )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def create_charts(
    charts_dir: Path,
    loaded: dict[str, tuple[list[dict], dict]],
    concurrencies: list[int],
) -> None:
    charts_dir.mkdir(parents=True, exist_ok=True)
    by_variant = {
        name: {int(row["concurrency"]): row for row in rows}
        for name, (rows, _manifest) in loaded.items()
    }
    throughput_series = [
        (
            spec.display_name,
            [
                finite(by_variant[spec.name][concurrency]["output_token_throughput_tps"])
                for concurrency in concurrencies
            ],
        )
        for spec in VARIANTS
    ]
    line_chart(
        charts_dir / "output-throughput.svg",
        "All variants: output token throughput",
        "Output tokens / second",
        concurrencies,
        throughput_series,
    )

    # Keep the executive chart intentionally small.  These five series are the
    # controlled comparisons used by the final report; the two legacy bundle
    # artifacts remain available in the full chart above.
    executive_variants = (
        "baseline",
        "baseline-cpu8",
        "mtp-cpu8",
        "mtp-kv768-cpu8",
        "mtp-seq24-cpu8",
    )
    executive_series = [
        (
            SPEC_BY_NAME[name].display_name,
            [
                finite(by_variant[name][concurrency]["output_token_throughput_tps"])
                for concurrency in concurrencies
            ],
        )
        for name in executive_variants
    ]
    line_chart(
        charts_dir / "core-throughput.svg",
        "Core controlled comparisons: output throughput",
        "Output tokens / second",
        concurrencies,
        executive_series,
    )

    baseline_series = []
    for spec in VARIANTS[1:]:
        baseline_series.append(
            (
                spec.display_name,
                [
                    percent_change(
                        by_variant["baseline"][concurrency]["output_token_throughput_tps"],
                        by_variant[spec.name][concurrency]["output_token_throughput_tps"],
                    )
                    for concurrency in concurrencies
                ],
            )
        )
    line_chart(
        charts_dir / "vs-cpu6-baseline.svg",
        "Output throughput change vs CPU6 baseline",
        "Percent",
        concurrencies,
        baseline_series,
    )

    direct_series = []
    for spec in VARIANTS:
        if spec.same_cpu_reference is None:
            continue
        direct_series.append(
            (
                f"{spec.display_name} vs {SPEC_BY_NAME[spec.same_cpu_reference].display_name}",
                [
                    percent_change(
                        by_variant[spec.same_cpu_reference][concurrency][
                            "output_token_throughput_tps"
                        ],
                        by_variant[spec.name][concurrency]["output_token_throughput_tps"],
                    )
                    for concurrency in concurrencies
                ],
            )
        )
    line_chart(
        charts_dir / "same-cpu-direct-effect.svg",
        "Same-CPU direct output-throughput effect",
        "Percent",
        concurrencies,
        direct_series,
    )
    kv_cache_tradeoff_chart(
        charts_dir / "kv-cache-tradeoff-c20.svg",
        by_variant,
    )
    kv_cache_growth_chart(
        charts_dir / "kv-cache-growth-by-concurrency.svg",
        by_variant,
        concurrencies,
    )


def write_report(
    output: Path,
    comparison_rows: list[dict[str, Any]],
) -> None:
    factor_table = [
        "| Artifact ID | 표시명 | CPU | MTP2 | KV | max-num-seqs | 분류 |",
        "|---|---|---:|---|---:|---:|---|",
    ]
    for spec in VARIANTS:
        classification = (
            "legacy capacity bundle; KV-only 아님"
            if spec.legacy_bundle
            else spec.direct_effect
        )
        factor_table.append(
            f"| `{spec.name}` | {spec.display_name} | {spec.cpu_limit} | "
            f"{'on' if spec.mtp_enabled else 'off'} | {spec.kv_mib}MiB | "
            f"{spec.max_num_seqs} | {classification} |"
        )

    result_table = [
        "| C | Variant | output tok/s | vs CPU6 baseline | same-CPU reference | direct effect | E2E p95 | run/wait |",
        "|---:|---|---:|---:|---|---:|---:|---:|",
    ]
    for row in comparison_rows:
        baseline_change = float(row["vs_cpu6_baseline_output_percent"])
        direct = (
            f"{float(row['same_cpu_direct_output_percent']):+.1f}%"
            if row["same_cpu_direct_output_percent"]
            else "—"
        )
        reference = (
            f"`{row['same_cpu_reference']}`" if row["same_cpu_reference"] else "—"
        )
        result_table.append(
            f"| {row['concurrency']} | `{row['variant']}` | "
            f"{float(row['output_tps']):.2f} | {baseline_change:+.1f}% | "
            f"{reference} | {direct} | {float(row['e2e_p95_seconds']):.2f}s | "
            f"{row['peak_running']}/{row['peak_waiting']} |"
        )

    report = f"""# 전체 CPU serving variant 종합 비교

## 검증

- 필수 variant `8`개, variant별 `700`건, 총 `5,600`건을 검증했다.
- 모든 run은 동일 prompt SHA-256, tokenized input, 모델, vLLM, workload config와 동시성 `1, 2, 5, 10, 20, 50, 100`을 사용한다.
- 각 phase는 `100/100` 성공, client/server prompt·generation token 합계 일치, metric scrape error와 OOM kill 0, wall/monotonic timer 허용 오차 통과 조건을 만족한다.
- captured image, env, container args와 CPU/memory resources를 아래 factor matrix의 기대값과 정확히 대조했다.

`mtp-kv-tuned`와 `mtp-kv-tuned-cpu8`은 보존된 역사적 artifact ID다. 두 설정은 KV `512→768MiB`와 `max-num-seqs 20→24`를 동시에 변경한 **legacy capacity bundle**이며 KV-only 최적화로 해석하지 않는다.

## Factor matrix

{chr(10).join(factor_table)}

## 동시성별 실측

`vs CPU6 baseline`은 같은 동시성의 `baseline` 대비 값이다. `direct effect`는 CPU를 고정한 직전 reference 대비 값이므로 MTP, KV-only, maxseq-only 및 legacy bundle의 증분 효과를 나타낸다. `baseline-cpu8`의 CPU 변경 효과는 `vs CPU6 baseline` 열에서 확인한다.

`run/wait`는 각 metric 시계열에서 독립적으로 구한 peak running / peak waiting이며, 같은 시점의 합으로 해석하지 않는다.

{chr(10).join(result_table)}

## 그래프

- [전체 output throughput](charts/output-throughput.svg)
- [핵심 단일 변수 비교](charts/core-throughput.svg)
- [CPU6 baseline 대비 변화율](charts/vs-cpu6-baseline.svg)
- [같은 CPU의 직전 단독/증분 효과](charts/same-cpu-direct-effect.svg)
- [동시성별 peak KV cache 점유](charts/kv-cache-growth-by-concurrency.svg)
- [KV cache capacity–performance trade-off (C=20)](charts/kv-cache-tradeoff-c20.svg)

원시 값과 전체 지표는 [comparison.csv](comparison.csv)에 저장한다. 단일 실행 간 host background load와 thermal 변동은 제거되지 않으므로 작은 차이는 반복 실험 없이 확정값으로 해석하지 않는다.
"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--results-root",
        type=Path,
        default=repository / "benchmark" / "results",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repository / "benchmark" / "results" / "comparison-all-variants",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        loaded = load_results(args.results_root)
        concurrencies = validate_results(args.results_root, loaded)
        comparison_rows = build_comparison_rows(loaded, concurrencies)
        args.output.mkdir(parents=True, exist_ok=True)
        write_csv(args.output / "comparison.csv", comparison_rows)
        create_charts(args.output / "charts", loaded, concurrencies)
        write_report(args.output, comparison_rows)
    except (ComparisonError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"Validated {len(VARIANTS)} variants and wrote {len(comparison_rows)} comparison rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
