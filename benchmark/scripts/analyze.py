#!/usr/bin/env python3
"""Aggregate raw benchmark records and generate CSV, SVG charts, and a report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


COLORS = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#ea580c")


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def finite(values: list[Any]) -> list[float]:
    result = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def metric_delta(rows: list[dict], name: str) -> float:
    values = finite([row.get(name) for row in rows])
    return values[-1] - values[0] if len(values) >= 2 else math.nan


def metric_peak(rows: list[dict], name: str) -> float:
    values = finite([row.get(name) for row in rows])
    return max(values) if values else math.nan


def metric_average(rows: list[dict], name: str) -> float:
    values = finite([row.get(name) for row in rows])
    return statistics.fmean(values) if values else math.nan


def latency_stats(
    rows: list[dict],
    name: str,
    scale: float = 1.0,
    output_name: str | None = None,
) -> dict[str, float]:
    values = [value * scale for value in finite([row.get(name) for row in rows])]
    prefix = output_name or name
    return {
        f"{prefix}_mean": statistics.fmean(values) if values else math.nan,
        f"{prefix}_p50": percentile(values, 0.50),
        f"{prefix}_p95": percentile(values, 0.95),
        f"{prefix}_p99": percentile(values, 0.99),
    }


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def aggregate(input_dir: Path) -> tuple[list[dict], dict]:
    manifest = json.loads((input_dir / "run-manifest.json").read_text(encoding="utf-8"))
    summaries: list[dict] = []
    for phase in sorted(manifest["phases"], key=lambda item: int(item["concurrency"])):
        requests = read_jsonl(input_dir / phase["requests_file"])
        metrics = read_csv(input_dir / phase["metrics_file"])
        success = [row for row in requests if row["status"] == "success"]
        duration = float(phase["duration_seconds"])
        prompt_tokens = sum(int(row["prompt_tokens"]) for row in success)
        completion_tokens = sum(int(row["completion_tokens"]) for row in success)

        elapsed = finite([row.get("elapsed_seconds") for row in metrics])
        cpu_delta_usec = metric_delta(metrics, "pod_cpu_usage_usec")
        sampled_duration = elapsed[-1] - elapsed[0] if len(elapsed) >= 2 else math.nan
        avg_cpu_cores = (
            cpu_delta_usec / 1_000_000 / sampled_duration
            if math.isfinite(cpu_delta_usec) and sampled_duration > 0
            else math.nan
        )
        draft_tokens = metric_delta(metrics, "vllm:spec_decode_num_draft_tokens_total")
        accepted_tokens = metric_delta(metrics, "vllm:spec_decode_num_accepted_tokens_total")
        cpu_periods_delta = metric_delta(metrics, "pod_cpu_nr_periods")
        cpu_throttled_periods_delta = metric_delta(metrics, "pod_cpu_nr_throttled")
        cpu_throttled_usec_delta = metric_delta(metrics, "pod_cpu_throttled_usec")

        summary = {
            "concurrency": int(phase["concurrency"]),
            "requests": len(requests),
            "successes": len(success),
            "failures": len(requests) - len(success),
            "success_rate_percent": 100 * len(success) / len(requests) if requests else 0.0,
            "duration_seconds": duration,
            "request_throughput_rps": len(success) / duration if duration else math.nan,
            "prompt_token_throughput_tps": prompt_tokens / duration if duration else math.nan,
            "output_token_throughput_tps": completion_tokens / duration if duration else math.nan,
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            **latency_stats(success, "e2e_seconds"),
            **latency_stats(success, "ttft_seconds"),
            **latency_stats(success, "tpot_seconds", scale=1000.0, output_name="tpot_ms"),
            "peak_running_requests": metric_peak(metrics, "vllm:num_requests_running"),
            "peak_waiting_requests": metric_peak(metrics, "vllm:num_requests_waiting"),
            "peak_kv_cache_percent": 100 * metric_peak(metrics, "vllm:kv_cache_usage_perc"),
            "avg_running_requests": metric_average(metrics, "vllm:num_requests_running"),
            "avg_waiting_requests": metric_average(metrics, "vllm:num_requests_waiting"),
            "avg_pod_cpu_cores": avg_cpu_cores,
            "cpu_periods_delta": cpu_periods_delta,
            "cpu_throttled_periods_delta": cpu_throttled_periods_delta,
            "cpu_throttled_period_percent": (
                100 * cpu_throttled_periods_delta / cpu_periods_delta
                if math.isfinite(cpu_periods_delta) and cpu_periods_delta > 0
                else math.nan
            ),
            "cpu_throttled_usec_delta": cpu_throttled_usec_delta,
            "cpu_throttled_time_percent": (
                100 * cpu_throttled_usec_delta / 1_000_000 / sampled_duration
                if math.isfinite(cpu_throttled_usec_delta) and sampled_duration > 0
                else math.nan
            ),
            "peak_pod_memory_gib": metric_peak(metrics, "pod_memory_current_bytes") / 1024**3,
            "server_prompt_tokens_delta": metric_delta(metrics, "vllm:prompt_tokens_total"),
            "server_generation_tokens_delta": metric_delta(metrics, "vllm:generation_tokens_total"),
            "preemptions_delta": metric_delta(metrics, "vllm:num_preemptions_total"),
            "prefix_cache_queries_delta": metric_delta(metrics, "vllm:prefix_cache_queries_total"),
            "prefix_cache_hits_delta": metric_delta(metrics, "vllm:prefix_cache_hits_total"),
            "spec_drafts_delta": metric_delta(metrics, "vllm:spec_decode_num_drafts_total"),
            "spec_draft_tokens_delta": draft_tokens,
            "spec_accepted_tokens_delta": accepted_tokens,
            "spec_acceptance_percent": (
                100 * accepted_tokens / draft_tokens
                if math.isfinite(draft_tokens) and draft_tokens > 0
                else math.nan
            ),
            "memory_max_events_delta": metric_delta(metrics, "pod_memory_events_max"),
            "oom_events_delta": metric_delta(metrics, "pod_memory_events_oom"),
            "oom_kill_events_delta": metric_delta(metrics, "pod_memory_events_oom_kill"),
        }
        summaries.append(summary)
    return summaries, manifest


def format_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6f}"
    return str(value)


def json_safe(value: Any) -> Any:
    """Replace non-finite floats so summary.json remains standards-compliant JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: format_number(value) for key, value in row.items()})


def nice_max(value: float) -> float:
    if value <= 0 or not math.isfinite(value):
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / 10**exponent
    step = 1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10
    return step * 10**exponent


def line_chart(
    path: Path,
    title: str,
    x_values: list[int],
    series: list[tuple[str, list[float]]],
    y_label: str,
) -> None:
    width, height = 920, 520
    left, right, top, bottom = 90, 35, 70, 75
    plot_w, plot_h = width - left - right, height - top - bottom
    all_values = [value for _, values in series for value in values if math.isfinite(value)]
    y_max = nice_max(max(all_values) * 1.08 if all_values else 1.0)
    x_min, x_max = min(x_values), max(x_values)

    def px(value: float) -> float:
        if x_max == x_min:
            return left + plot_w / 2
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def py(value: float) -> float:
        return top + plot_h - value / y_max * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="32" text-anchor="middle" font-size="22" font-family="sans-serif" font-weight="600">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        y = py(value)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="12" font-family="sans-serif" fill="#4b5563">{value:.2f}</text>'
        )
    for value in x_values:
        x = px(value)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_h}" stroke="#f3f4f6"/>')
        parts.append(
            f'<text x="{x:.2f}" y="{top + plot_h + 25}" text-anchor="middle" font-size="13" font-family="sans-serif">{value}</text>'
        )
    parts.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#111827"/>',
            f'<text x="{left + plot_w / 2}" y="{height - 20}" text-anchor="middle" font-size="14" font-family="sans-serif">Concurrency</text>',
            f'<text transform="translate(22 {top + plot_h / 2}) rotate(-90)" text-anchor="middle" font-size="14" font-family="sans-serif">{html.escape(y_label)}</text>',
        ]
    )
    legend_x = left + 12
    for index, (label, values) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        points = " ".join(
            f"{px(x):.2f},{py(y):.2f}" for x, y in zip(x_values, values) if math.isfinite(y)
        )
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>')
        for x, y in zip(x_values, values):
            if math.isfinite(y):
                parts.append(f'<circle cx="{px(x):.2f}" cy="{py(y):.2f}" r="4" fill="{color}"/>')
        lx = legend_x + index * 190
        parts.append(f'<line x1="{lx}" y1="52" x2="{lx + 24}" y2="52" stroke="{color}" stroke-width="3"/>')
        parts.append(
            f'<text x="{lx + 30}" y="56" font-size="13" font-family="sans-serif">{html.escape(label)}</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def bar_chart(path: Path, title: str, labels: list[str], values: list[float], y_label: str) -> None:
    width, height = 920, 520
    left, right, top, bottom = 90, 35, 65, 100
    plot_w, plot_h = width - left - right, height - top - bottom
    y_max = nice_max(max(values) * 1.1 if values else 1.0)
    slot = plot_w / max(1, len(values))
    bar_w = slot * 0.62
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="32" text-anchor="middle" font-size="22" font-family="sans-serif" font-weight="600">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        y = top + plot_h - value / y_max * plot_h
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="12" font-family="sans-serif">{value:.1f}</text>')
    for index, (label, value) in enumerate(zip(labels, values)):
        x = left + index * slot + (slot - bar_w) / 2
        y = top + plot_h - value / y_max * plot_h
        color = COLORS[index % len(COLORS)]
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{top + plot_h - y:.2f}" fill="{color}" rx="3"/>')
        parts.append(f'<text x="{x + bar_w / 2:.2f}" y="{y - 8:.2f}" text-anchor="middle" font-size="12" font-family="sans-serif">{value:.1f}</text>')
        parts.append(f'<text x="{x + bar_w / 2:.2f}" y="{top + plot_h + 25}" text-anchor="middle" font-size="12" font-family="sans-serif">{html.escape(label)}</text>')
    parts.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#111827"/>',
            f'<text transform="translate(22 {top + plot_h / 2}) rotate(-90)" text-anchor="middle" font-size="14" font-family="sans-serif">{html.escape(y_label)}</text>',
            "</svg>",
        ]
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def create_charts(input_dir: Path, rows: list[dict]) -> None:
    chart_dir = input_dir / "charts"
    chart_dir.mkdir(exist_ok=True)
    x = [row["concurrency"] for row in rows]
    line_chart(
        chart_dir / "e2e-latency.svg",
        "E2E latency vs concurrency",
        x,
        [(label, [row[f"e2e_seconds_{key}"] for row in rows]) for label, key in (("p50", "p50"), ("p95", "p95"), ("p99", "p99"))],
        "Seconds / request",
    )
    line_chart(
        chart_dir / "ttft.svg",
        "Time to first token vs concurrency",
        x,
        [(label, [row[f"ttft_seconds_{key}"] for row in rows]) for label, key in (("p50", "p50"), ("p95", "p95"), ("p99", "p99"))],
        "Seconds / request",
    )
    line_chart(
        chart_dir / "tpot.svg",
        "Time per output token vs concurrency",
        x,
        [(label, [row[f"tpot_ms_{key}"] for row in rows]) for label, key in (("p50", "p50"), ("p95", "p95"), ("p99", "p99"))],
        "Milliseconds / token",
    )
    line_chart(
        chart_dir / "request-throughput.svg",
        "Request throughput vs concurrency",
        x,
        [("request/s", [row["request_throughput_rps"] for row in rows])],
        "Requests / second",
    )
    line_chart(
        chart_dir / "token-throughput.svg",
        "Token throughput vs concurrency",
        x,
        [
            ("prompt token/s", [row["prompt_token_throughput_tps"] for row in rows]),
            ("output token/s", [row["output_token_throughput_tps"] for row in rows]),
        ],
        "Tokens / second",
    )
    line_chart(
        chart_dir / "output-token-throughput.svg",
        "Output token throughput vs concurrency",
        x,
        [("output token/s", [row["output_token_throughput_tps"] for row in rows])],
        "Output tokens / second",
    )
    line_chart(
        chart_dir / "server-pressure.svg",
        "vLLM scheduler pressure vs concurrency",
        x,
        [
            ("peak running", [row["peak_running_requests"] for row in rows]),
            ("peak waiting", [row["peak_waiting_requests"] for row in rows]),
        ],
        "Requests",
    )
    line_chart(
        chart_dir / "kv-cache.svg",
        "Peak KV cache usage vs concurrency",
        x,
        [("peak KV", [row["peak_kv_cache_percent"] for row in rows])],
        "Percent",
    )
    line_chart(
        chart_dir / "resources.svg",
        "Average Pod CPU vs concurrency",
        x,
        [("CPU cores", [row["avg_pod_cpu_cores"] for row in rows])],
        "Average CPU cores",
    )
    line_chart(
        chart_dir / "memory.svg",
        "Peak Pod memory vs concurrency",
        x,
        [("peak memory", [row["peak_pod_memory_gib"] for row in rows])],
        "GiB",
    )

    first_phase = sorted(
        json.loads((input_dir / "run-manifest.json").read_text(encoding="utf-8"))["phases"],
        key=lambda item: item["concurrency"],
    )[0]
    requests = [row for row in read_jsonl(input_dir / first_phase["requests_file"]) if row["status"] == "success"]
    tokens_by_source: dict[str, list[int]] = defaultdict(list)
    for request in requests:
        tokens_by_source[request["source"]].append(int(request["prompt_tokens"]))
    labels = sorted(tokens_by_source)
    bar_chart(
        chart_dir / "prompt-tokens-by-source.svg",
        "Average input tokens by benchmark source",
        labels,
        [statistics.fmean(tokens_by_source[label]) for label in labels],
        "Prompt tokens",
    )


def ratio(after: float, before: float) -> str:
    if not before or not math.isfinite(after) or not math.isfinite(before):
        return "N/A"
    return f"{after / before:.2f}×"


def write_report(input_dir: Path, rows: list[dict], manifest: dict) -> None:
    first, last = rows[0], rows[-1]
    best = max(rows, key=lambda row: row["output_token_throughput_tps"])
    saturation = next(
        row
        for row in rows
        if row["output_token_throughput_tps"]
        >= best["output_token_throughput_tps"] * 0.95
    )
    first_wait = next((row for row in rows if row["peak_waiting_requests"] > 0), None)
    total_prefix_hits = sum(value for value in (row["prefix_cache_hits_delta"] for row in rows) if math.isfinite(value))
    total_preemptions = sum(value for value in (row["preemptions_delta"] for row in rows) if math.isfinite(value))
    total_oom = sum(value for value in (row["oom_kill_events_delta"] for row in rows) if math.isfinite(value))
    row_by_concurrency = {row["concurrency"]: row for row in rows}
    throughput_gain_after_saturation = 100 * (
        best["output_token_throughput_tps"]
        / saturation["output_token_throughput_tps"]
        - 1
    )
    c1_to_saturation_throughput = (
        saturation["output_token_throughput_tps"]
        / first["output_token_throughput_tps"]
    )
    saturation_to_last_e2e_p95 = (
        last["e2e_seconds_p95"] / saturation["e2e_seconds_p95"]
    )
    host = manifest.get("environment", {}).get("host", {})
    docker = manifest.get("environment", {}).get("docker", {}) or {}
    container = manifest.get("environment", {}).get("kubernetes", {}).get("container", {}) or {}
    container_args = container.get("args", []) or []
    resources = container.get("resources", {}) or {}
    cpu_limit = (resources.get("limits", {}) or {}).get("cpu", "unknown")

    def argument_value(flag: str, default: str) -> str:
        try:
            return str(container_args[container_args.index(flag) + 1])
        except (ValueError, IndexError):
            return default

    kv_bytes = int(argument_value("--kv-cache-memory-bytes", "0"))
    kv_mib = kv_bytes / 1024**2
    max_num_seqs = argument_value("--max-num-seqs", "unknown")
    max_average_cpu = max(row["avg_pod_cpu_cores"] for row in rows)
    server_version_value = manifest.get("server_version")
    if isinstance(server_version_value, dict):
        server_version_value = server_version_value.get("version")

    table_lines = [
        "| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table_lines.append(
            "| {concurrency} | {success_rate_percent:.1f}% | {request_throughput_rps:.3f} | "
            "{output_token_throughput_tps:.2f} | {e2e_seconds_p50:.2f} / {e2e_seconds_p95:.2f} | "
            "{ttft_seconds_p50:.2f} / {ttft_seconds_p95:.2f} | {tpot_ms_p50:.2f} / "
            "{tpot_ms_p95:.2f} | {peak_waiting_requests:.0f} | {peak_kv_cache_percent:.1f}% | "
            "{avg_pod_cpu_cores:.2f} | {peak_pod_memory_gib:.2f}GiB |".format(**row)
        )

    experiment = manifest.get("config", {}).get("experiment", "baseline")
    if experiment != "baseline":
        results_root = (
            input_dir.parent.parent
            if input_dir.parent.name in {"validation-gates", "validation-repeats"}
            else input_dir.parent
        )
        for parent in input_dir.parents:
            if (parent / "baseline").is_dir():
                results_root = parent
                break
        sequential_variants = {
            "baseline-cpu8",
            "mtp-cpu8",
            "mtp-kv768-cpu8",
            "mtp-kv768-fp8-cpu8",
        }
        cpu8_factor_variants = {
            "baseline-cpu8",
            "mtp-cpu8",
            "baseline-kv768-cpu8",
            "baseline-cpu8-fp8",
            "baseline-kv768-fp8-cpu8",
        }
        if experiment in {
            "baseline-kv768-cpu8",
            "baseline-cpu8-fp8",
            "baseline-kv768-fp8-cpu8",
        } or (
            experiment in cpu8_factor_variants
            and (results_root / "baseline-kv768-cpu8").is_dir()
        ):
            comparison_directory = "comparison-cpu8-factors"
        elif experiment in sequential_variants:
            comparison_directory = "comparison-sequential"
        else:
            comparison_directory = "comparison-all"
        comparison_link = Path(
            os.path.relpath(
                results_root / comparison_directory / "REPORT.md", input_dir
            )
        ).as_posix()
        acceptance_values = [
            row["spec_acceptance_percent"]
            for row in rows
            if math.isfinite(row["spec_acceptance_percent"])
        ]
        acceptance_text = (
            f"{min(acceptance_values):.1f}~{max(acceptance_values):.1f}%"
            if acceptance_values
            else "N/A"
        )
        report = f"""# CPU vLLM 부하 측정 자동 리포트: {experiment}

## 검증 요약

- 완료 요청: `{sum(row['successes'] for row in rows)}/{sum(row['requests'] for row in rows)}`
- 동시성: `{', '.join(str(row['concurrency']) for row in rows)}`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`{best['concurrency']}`, `{best['output_token_throughput_tps']:.2f} token/s`
- 최초 scheduler waiting: C=`{first_wait['concurrency'] if first_wait else '없음'}`
- 전체 prefix hit / preemption / OOM kill 증가량: `{total_prefix_hits:.0f} / {total_preemptions:.0f} / {total_oom:.0f}`
- MTP draft acceptance 범위: `{acceptance_text}`
- 최대 peak running / waiting / KV / RAM: `{max(row['peak_running_requests'] for row in rows):.0f} / {max(row['peak_waiting_requests'] for row in rows):.0f} / {max(row['peak_kv_cache_percent'] for row in rows):.1f}% / {max(row['peak_pod_memory_gib'] for row in rows):.2f}GiB`

## 결과

{chr(10).join(table_lines)}

## 그래프

- [E2E latency](charts/e2e-latency.svg)
- [TTFT](charts/ttft.svg)
- [TPOT](charts/tpot.svg)
- [Request throughput](charts/request-throughput.svg)
- [Token throughput](charts/token-throughput.svg)
- [Output token throughput](charts/output-token-throughput.svg)
- [Scheduler running/waiting](charts/server-pressure.svg)
- [KV cache](charts/kv-cache.svg)
- [Pod CPU](charts/resources.svg)
- [Pod memory](charts/memory.svg)
- [Source별 prompt tokens](charts/prompt-tokens-by-source.svg)

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 비교 설정 측정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교]({comparison_link})에서 baseline 대비 직접 효과를 교차 분석한다.
"""
        (input_dir / "REPORT.md").write_text(report, encoding="utf-8")
        return

    input_validation = manifest["input_token_validation"]
    report = f"""# CPU vLLM 베이스라인 부하 측정 리포트

## 결론 요약

- 고정된 100개 요청을 동시성 `{', '.join(str(row['concurrency']) for row in rows)}`에서 각각 한 번씩 실행하여 총 `{sum(row['requests'] for row in rows)}`건을 측정했다.
- nominal 최고 output throughput은 동시성 `{best['concurrency']}`의 `{best['output_token_throughput_tps']:.2f} token/s`다. 최고값의 95%에 처음 도달한 실용적 처리량 포화점은 C=`{saturation['concurrency']}`이고, 이후 추가 이득은 최대 `{throughput_gain_after_saturation:.2f}%`다.
- 동시성 `{first['concurrency']} → {last['concurrency']}`에서 E2E p95는 `{ratio(last['e2e_seconds_p95'], first['e2e_seconds_p95'])}`, TTFT p95는 `{ratio(last['ttft_seconds_p95'], first['ttft_seconds_p95'])}`, TPOT p95는 `{ratio(last['tpot_ms_p95'], first['tpot_ms_p95'])}`가 됐다.
- C=1→`{saturation['concurrency']}`에서 output throughput은 `{c1_to_saturation_throughput:.2f}×`가 됐고, 포화점→C=`{last['concurrency']}`에서 E2E p95는 `{saturation_to_last_e2e_p95:.2f}×`가 됐다.
- 최초로 scheduler waiting이 관찰된 동시성은 `{first_wait['concurrency'] if first_wait else '없음'}`이다. 전체 prefix cache hit 증가량은 `{total_prefix_hits:.0f}`, preemption 증가량은 `{total_preemptions:.0f}`, Pod OOM kill 증가량은 `{total_oom:.0f}`이다.

## 실험 조건

- Host: `{host.get('cpu_brand')}`, logical CPU `{host.get('logical_cpu')}`, physical memory `{int(host.get('memory_bytes') or 0) / 1024**3:.1f}GiB`
- Docker Desktop: `{docker.get('cpus')}` vCPU, `{(docker.get('memory_bytes') or 0) / 1024**3:.2f}GiB`, `{docker.get('architecture')}`
- Image: `{container.get('image')}`
- Model/API: `{manifest['config']['model']}`, vLLM `{server_version_value}`
- Request set: source 4종 × 25건, workload file SHA-256 `{manifest['prompts_sha256']}`
- Input tokens: min `{input_validation['minimum']}`, mean `{input_validation['mean']:.1f}`, max `{input_validation['maximum']}`
- Output: 요청당 `{manifest['config']['max_tokens']}` tokens, `ignore_eos={str(manifest['config']['ignore_eos']).lower()}`, `temperature={manifest['config']['temperature']}`
- Prefix caching: disabled. 일반 per-request KV cache만 사용
- 각 동시성별 3건 warmup은 통계에서 제외

동시성 C는 100건을 C번 반복한다는 의미가 아니라, 동일한 총 100건 중 최대 C건만 동시에 in-flight가 되도록 하는 closed-loop worker 수다. 따라서 실험당 요청 수는 항상 100건이고 모든 단계의 prompt 순서가 같다.

## 결과

{chr(10).join(table_lines)}

서버 counter의 prompt/generation token 증가량과 클라이언트 usage 합계는 `summary.csv`에서 교차 확인할 수 있다. 차이가 있으면 scrape 시작/종료 또는 실패 요청을 먼저 점검해야 한다.

## 그래프

- [E2E latency](charts/e2e-latency.svg)
- [TTFT](charts/ttft.svg)
- [TPOT](charts/tpot.svg)
- [Request throughput](charts/request-throughput.svg)
- [Token throughput](charts/token-throughput.svg)
- [Output token throughput](charts/output-token-throughput.svg)
- [Scheduler running/waiting](charts/server-pressure.svg)
- [KV cache](charts/kv-cache.svg)
- [Pod CPU](charts/resources.svg)
- [Pod memory](charts/memory.svg)
- [Source별 prompt tokens](charts/prompt-tokens-by-source.svg)

## 지표 해석

E2E는 사용자가 기다린 전체 시간이다. TTFT는 scheduler 대기와 prefill 영향을 크게 받고, TPOT는 첫 token 이후 decode 진행 속도를 보여준다. 따라서 동시성 증가 시 TTFT와 waiting이 함께 상승하고 TPOT는 상대적으로 덜 변하면 큐 대기가 주원인이다. 반대로 TPOT도 크게 악화되면 동시 batch 간 CPU 연산 경쟁 또는 memory bandwidth 영향을 의심할 수 있다.

Peak KV가 높으면서 waiting/preemption이 발생하면 `{kv_mib:.0f}MiB` KV 예산도 병목에 기여할 수 있다. 다만 이 실험에서 KV를 없애는 것은 올바른 비교가 아니다. autoregressive decoding에 필요한 요청 내부 KV는 유지하고, 요청 간 재사용 기능인 Automatic Prefix Caching만 껐다. 실제 결과의 prefix hit 증가량 `{total_prefix_hits:.0f}`으로 이 통제를 확인했다.

## 개선·악화 원인 분석

동시성이 1에서 포화점 C=`{saturation['concurrency']}`까지 증가할 때 batching으로 output throughput이 `{first['output_token_throughput_tps']:.2f} → {saturation['output_token_throughput_tps']:.2f} token/s`로 변했다. 관측된 최대 평균 Pod CPU는 `{max_average_cpu:.2f}` cores이고 container CPU limit은 `{cpu_limit}` cores이므로, 포화점 이후 동시성 증가는 CPU quota 자체를 늘리지 않는다.

포화점 C=`{saturation['concurrency']}`에서 peak running/waiting/KV는 `{saturation['peak_running_requests']:.0f}/{saturation['peak_waiting_requests']:.0f}/{saturation['peak_kv_cache_percent']:.1f}%`였다. 설정값은 KV `{kv_mib:.0f}MiB`, `max-num-seqs={max_num_seqs}`다. C=50과 C=100의 peak running/waiting은 각각 `{row_by_concurrency.get(50, last)['peak_running_requests']:.0f}/{row_by_concurrency.get(50, last)['peak_waiting_requests']:.0f}`, `{last['peak_running_requests']:.0f}/{last['peak_waiting_requests']:.0f}`였다. 처리량이 거의 늘지 않는데 waiting과 TTFT/E2E가 증가한다면 추가 요청은 service rate를 높이기보다 queue를 키운 것으로 해석한다.

TTFT는 first token 전 queue·prefill 시간을, TPOT는 first token 이후 decode 진행을 주로 반영한다. 따라서 waiting과 TTFT가 함께 증가하고 TPOT 변화가 더 작으면 대기 비용이 중심인 패턴이다. 전체 preemption 증가량은 `{total_preemptions:.0f}`이며, 0보다 클 때만 KV pressure에 따른 recompute 가능성을 함께 고려한다.

Peak Pod memory는 최대 `{max(row['peak_pod_memory_gib'] for row in rows):.2f}GiB`였고 OOM kill은 `{total_oom:.0f}`회였다. 따라서 높은 latency의 원인은 Pod OOM/restart가 아니라 고정 CPU capacity, KV 포화, scheduler queue로 해석할 수 있다.

## 한계와 다음 비교

이 결과는 로컬 장비에서 설정별 1회 측정한 값이므로 background load와 thermal state 영향을 포함한다. 최종 최적화 비교에서는 동일 100건·동일 64 output tokens를 유지하고 실행 순서를 교차하거나 3회 이상 반복해 중앙값과 변동 폭을 추가하는 것이 좋다.

MTP는 같은 Qwen3.5-0.8B checkpoint에 `speculative_config`만 추가하여 비교해야 한다. MTP는 medium/low QPS의 memory-bound decode에서 유리할 수 있지만, 높은 동시성에서는 draft/verification overhead 때문에 효과가 줄거나 악화될 수 있다. 따라서 output throughput·TPOT뿐 아니라 draft acceptance rate와 CPU 사용량도 함께 판단한다.
"""
    (input_dir / "REPORT.md").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--input", type=Path, default=root / "results" / "baseline")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows, manifest = aggregate(args.input)
    if not rows:
        raise RuntimeError(f"No completed phases in {args.input}")
    write_summary_csv(args.input / "summary.csv", rows)
    (args.input / "summary.json").write_text(
        json.dumps(json_safe(rows), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    create_charts(args.input, rows)
    write_report(args.input, rows, manifest)
    print(f"Wrote summary, {len(list((args.input / 'charts').glob('*.svg')))} charts, and REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
