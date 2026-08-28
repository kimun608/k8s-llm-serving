#!/usr/bin/env python3
"""Validate and compare baseline, MTP, and MTP+KV benchmark summaries."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from analyze import line_chart


VARIANT_ORDER = ("baseline", "mtp", "mtp-kv-tuned")
DISPLAY_NAMES = {
    "baseline": "Baseline",
    "mtp": "MTP2",
    "mtp-kv-tuned": "MTP2 + KV tuned",
}
FIXED_CONFIG_KEYS = (
    "model",
    "namespace",
    "service",
    "request_count",
    "concurrencies",
    "max_tokens",
    "temperature",
    "ignore_eos",
    "seed",
    "warmup_requests",
    "warmup_max_tokens",
    "cooldown_seconds",
    "metrics_interval_seconds",
    "system_prompt",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def percent_change(before: Any, after: Any) -> float:
    before_number, after_number = finite(before), finite(after)
    if not math.isfinite(before_number) or not math.isfinite(after_number) or before_number == 0:
        return math.nan
    return 100 * (after_number / before_number - 1)


def fmt(value: Any, digits: int = 2) -> str:
    number = finite(value)
    return "" if not math.isfinite(number) else f"{number:.{digits}f}"


def load_variant(path: Path) -> tuple[list[dict], dict]:
    summary_path = path / "summary.json"
    manifest_path = path / "run-manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"Missing analyzed benchmark files under {path}")
    rows = read_json(summary_path)
    manifest = read_json(manifest_path)
    return sorted(rows, key=lambda row: int(row["concurrency"])), manifest


def validate(variants: dict[str, tuple[list[dict], dict]]) -> list[int]:
    baseline_rows, baseline_manifest = variants["baseline"]
    concurrencies = [int(row["concurrency"]) for row in baseline_rows]
    baseline_config = baseline_manifest["config"]
    baseline_prompt_hash = baseline_manifest["prompts_sha256"]
    for name, (rows, manifest) in variants.items():
        if manifest.get("status") != "completed":
            raise ValueError(f"Run {name} is not completed")
        current = [int(row["concurrency"]) for row in rows]
        if current != concurrencies:
            raise ValueError(f"Concurrency mismatch for {name}: {current} != {concurrencies}")
        if manifest["prompts_sha256"] != baseline_prompt_hash:
            raise ValueError(f"Prompt file SHA-256 mismatch for {name}")
        for key in FIXED_CONFIG_KEYS:
            if manifest["config"].get(key) != baseline_config.get(key):
                raise ValueError(f"Fixed config mismatch for {name}: {key}")
        phases = {
            int(phase["concurrency"]): phase for phase in manifest.get("phases", [])
        }
        for row in rows:
            if int(row["requests"]) != 100 or int(row["successes"]) != 100:
                raise ValueError(f"Incomplete phase for {name} C={row['concurrency']}")
            if int(finite(row["total_prompt_tokens"])) != int(finite(row["server_prompt_tokens_delta"])):
                raise ValueError(f"Prompt token mismatch for {name} C={row['concurrency']}")
            if int(finite(row["total_completion_tokens"])) != int(finite(row["server_generation_tokens_delta"])):
                raise ValueError(f"Generation token mismatch for {name} C={row['concurrency']}")
            phase = phases.get(int(row["concurrency"]))
            if phase is None:
                raise ValueError(f"Missing phase metadata for {name} C={row['concurrency']}")
            wall_seconds = (
                datetime.fromisoformat(phase["finished_at_utc"])
                - datetime.fromisoformat(phase["started_at_utc"])
            ).total_seconds()
            timer_gap = abs(wall_seconds - finite(phase["duration_seconds"]))
            if timer_gap > max(5.0, finite(phase["duration_seconds"]) * 0.01):
                raise ValueError(
                    f"Host interruption detected for {name} C={row['concurrency']}: "
                    f"wall/timer gap={timer_gap:.2f}s"
                )
            if phase.get("metrics_scrape_errors"):
                raise ValueError(f"Metric scrape failed for {name} C={row['concurrency']}")
    return concurrencies


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("benchmark/results"))
    parser.add_argument("--output", type=Path, default=Path("benchmark/results/comparison"))
    args = parser.parse_args()

    variants = {
        name: load_variant(args.results_root / name)
        for name in VARIANT_ORDER
    }
    concurrencies = validate(variants)
    args.output.mkdir(parents=True, exist_ok=True)
    charts_dir = args.output / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    by_variant = {
        name: {int(row["concurrency"]): row for row in rows}
        for name, (rows, _manifest) in variants.items()
    }
    comparison_rows: list[dict] = []
    for concurrency in concurrencies:
        baseline = by_variant["baseline"][concurrency]
        mtp = by_variant["mtp"][concurrency]
        final = by_variant["mtp-kv-tuned"][concurrency]
        comparison_rows.append(
            {
                "concurrency": concurrency,
                "baseline_output_tps": fmt(baseline["output_token_throughput_tps"], 6),
                "mtp_output_tps": fmt(mtp["output_token_throughput_tps"], 6),
                "final_output_tps": fmt(final["output_token_throughput_tps"], 6),
                "mtp_vs_baseline_output_percent": fmt(percent_change(baseline["output_token_throughput_tps"], mtp["output_token_throughput_tps"]), 6),
                "final_vs_baseline_output_percent": fmt(percent_change(baseline["output_token_throughput_tps"], final["output_token_throughput_tps"]), 6),
                "kv_vs_mtp_output_percent": fmt(percent_change(mtp["output_token_throughput_tps"], final["output_token_throughput_tps"]), 6),
                "baseline_e2e_p95_seconds": fmt(baseline["e2e_seconds_p95"], 6),
                "mtp_e2e_p95_seconds": fmt(mtp["e2e_seconds_p95"], 6),
                "final_e2e_p95_seconds": fmt(final["e2e_seconds_p95"], 6),
                "final_vs_baseline_e2e_p95_percent": fmt(percent_change(baseline["e2e_seconds_p95"], final["e2e_seconds_p95"]), 6),
                "baseline_ttft_p95_seconds": fmt(baseline["ttft_seconds_p95"], 6),
                "mtp_ttft_p95_seconds": fmt(mtp["ttft_seconds_p95"], 6),
                "final_ttft_p95_seconds": fmt(final["ttft_seconds_p95"], 6),
                "final_vs_baseline_ttft_p95_percent": fmt(percent_change(baseline["ttft_seconds_p95"], final["ttft_seconds_p95"]), 6),
                "baseline_tpot_p95_ms": fmt(baseline["tpot_seconds_p95"], 6),
                "mtp_tpot_p95_ms": fmt(mtp["tpot_seconds_p95"], 6),
                "final_tpot_p95_ms": fmt(final["tpot_seconds_p95"], 6),
                "final_vs_baseline_tpot_p95_percent": fmt(percent_change(baseline["tpot_seconds_p95"], final["tpot_seconds_p95"]), 6),
                "baseline_peak_running": fmt(baseline["peak_running_requests"], 0),
                "mtp_peak_running": fmt(mtp["peak_running_requests"], 0),
                "final_peak_running": fmt(final["peak_running_requests"], 0),
                "baseline_peak_waiting": fmt(baseline["peak_waiting_requests"], 0),
                "mtp_peak_waiting": fmt(mtp["peak_waiting_requests"], 0),
                "final_peak_waiting": fmt(final["peak_waiting_requests"], 0),
                "baseline_peak_memory_gib": fmt(baseline["peak_pod_memory_gib"], 6),
                "mtp_peak_memory_gib": fmt(mtp["peak_pod_memory_gib"], 6),
                "final_peak_memory_gib": fmt(final["peak_pod_memory_gib"], 6),
                "mtp_acceptance_percent": fmt(mtp["spec_acceptance_percent"], 6),
                "final_acceptance_percent": fmt(final["spec_acceptance_percent"], 6),
            }
        )
    write_csv(args.output / "comparison.csv", comparison_rows)

    chart_specs = (
        ("output-token-throughput.svg", "Output token throughput", "token/s", "output_token_throughput_tps"),
        ("e2e-p95.svg", "E2E latency p95", "seconds", "e2e_seconds_p95"),
        ("ttft-p95.svg", "TTFT p95", "seconds", "ttft_seconds_p95"),
        ("tpot-p95.svg", "TPOT p95", "milliseconds/token", "tpot_seconds_p95"),
        ("peak-running.svg", "Peak running requests", "requests", "peak_running_requests"),
        ("peak-waiting.svg", "Peak waiting requests", "requests", "peak_waiting_requests"),
        ("kv-cache.svg", "Peak KV cache usage", "percent", "peak_kv_cache_percent"),
        ("pod-memory.svg", "Peak Pod memory", "GiB", "peak_pod_memory_gib"),
        ("pod-cpu.svg", "Average Pod CPU", "cores", "avg_pod_cpu_cores"),
    )
    for filename, title, unit, metric in chart_specs:
        series = [
            (
                DISPLAY_NAMES[name],
                [finite(by_variant[name][concurrency][metric]) for concurrency in concurrencies],
            )
            for name in VARIANT_ORDER
        ]
        line_chart(charts_dir / filename, title, concurrencies, series, unit)

    acceptance_series = [
        (
            DISPLAY_NAMES[name],
            [finite(by_variant[name][concurrency]["spec_acceptance_percent"]) for concurrency in concurrencies],
        )
        for name in ("mtp", "mtp-kv-tuned")
    ]
    line_chart(charts_dir / "mtp-acceptance.svg", "MTP acceptance rate", concurrencies, acceptance_series, "percent")

    table = [
        "| C | Baseline / MTP / Combined output tok/s | Combined vs base | Baseline / Combined E2E p95 | Combined vs base | Base / MTP / Combined peak wait | Combined acceptance |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison_rows:
        table.append(
            f"| {row['concurrency']} | {float(row['baseline_output_tps']):.2f} / {float(row['mtp_output_tps']):.2f} / {float(row['final_output_tps']):.2f} | "
            f"{float(row['final_vs_baseline_output_percent']):+.1f}% | {float(row['baseline_e2e_p95_seconds']):.2f}s / {float(row['final_e2e_p95_seconds']):.2f}s | "
            f"{float(row['final_vs_baseline_e2e_p95_percent']):+.1f}% | {row['baseline_peak_waiting']} / {row['mtp_peak_waiting']} / {row['final_peak_waiting']} | "
            f"{float(row['final_acceptance_percent']):.1f}% |"
        )

    total_requests = sum(int(row["requests"]) for name in VARIANT_ORDER for row in by_variant[name].values())
    total_failures = sum(int(row["failures"]) for name in VARIANT_ORDER for row in by_variant[name].values())
    total_oom = sum(finite(row["oom_kill_events_delta"]) for name in VARIANT_ORDER for row in by_variant[name].values())
    report = f"""# Baseline vs MTP vs MTP+KV 자동 비교

## 검증

- 비교 요청: `{total_requests}`건, 실패 `{total_failures}`건
- 세 설정의 prompt file SHA-256, 모델, 100건, 출력 64 tokens, 동시성, sampling, warmup/cooldown가 동일함
- client/server prompt와 generation token counter가 모든 단계에서 일치함
- 정식 phase의 UTC wall clock과 monotonic timer 오차가 1%/5초 이내이며 metric scrape error가 없음
- 전체 OOM kill 증가량: `{total_oom:.0f}`

## 결과

{chr(10).join(table)}

## 그래프

- [Output throughput](charts/output-token-throughput.svg)
- [E2E p95](charts/e2e-p95.svg)
- [TTFT p95](charts/ttft-p95.svg)
- [TPOT p95](charts/tpot-p95.svg)
- [Peak running](charts/peak-running.svg)
- [Peak waiting](charts/peak-waiting.svg)
- [KV cache](charts/kv-cache.svg)
- [Pod memory](charts/pod-memory.svg)
- [Pod CPU](charts/pod-cpu.svg)
- [MTP acceptance](charts/mtp-acceptance.svg)

이 문서는 원시 summary에서 자동 생성한 사실표다. 개선·악화 원인, FP8 실패, GPU 프로덕션 전환 판단은 [최종 분석 리포트](../../../reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)에 별도로 서술한다.
"""
    (args.output / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"Validated {total_requests} requests and wrote {len(chart_specs) + 1} comparison charts")


if __name__ == "__main__":
    main()
