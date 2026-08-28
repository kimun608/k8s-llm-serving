#!/usr/bin/env python3
"""Validate the one-field CPU limit experiment and compare it with baseline."""

from __future__ import annotations

import argparse
import copy
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from analyze import line_chart
from compare import finite, fmt, load_variant, percent_change, write_csv


VARIANTS = ("baseline", "baseline-cpu8")
DISPLAY_NAMES = {"baseline": "CPU limit 6", "baseline-cpu8": "CPU limit 8"}


def without_experiment(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized.pop("experiment", None)
    return normalized


def validate_single_serving_change(baseline_manifest: dict, cpu8_manifest: dict) -> None:
    baseline_container = copy.deepcopy(
        baseline_manifest["environment"]["kubernetes"]["container"]
    )
    cpu8_container = copy.deepcopy(
        cpu8_manifest["environment"]["kubernetes"]["container"]
    )
    baseline_cpu = baseline_container["resources"]["limits"].get("cpu")
    cpu8_cpu = cpu8_container["resources"]["limits"].get("cpu")
    if str(baseline_cpu) != "6" or str(cpu8_cpu) != "8":
        raise ValueError(
            f"Expected only CPU limits 6 -> 8, found {baseline_cpu!r} -> {cpu8_cpu!r}"
        )
    cpu8_container["resources"]["limits"]["cpu"] = baseline_cpu
    if cpu8_container != baseline_container:
        raise ValueError(
            "Container image, args, env, requests, memory, or another resource changed"
        )


def validate(variants: dict[str, tuple[list[dict], dict]]) -> list[int]:
    baseline_rows, baseline_manifest = variants["baseline"]
    cpu8_rows, cpu8_manifest = variants["baseline-cpu8"]
    concurrencies = [int(row["concurrency"]) for row in baseline_rows]
    if [int(row["concurrency"]) for row in cpu8_rows] != concurrencies:
        raise ValueError("Concurrency matrix differs from baseline")
    if without_experiment(cpu8_manifest["config"]) != without_experiment(
        baseline_manifest["config"]
    ):
        raise ValueError("Benchmark config differs by more than experiment name")
    if cpu8_manifest["prompts_sha256"] != baseline_manifest["prompts_sha256"]:
        raise ValueError("Prompt file SHA-256 differs from baseline")
    if cpu8_manifest["input_token_validation"] != baseline_manifest["input_token_validation"]:
        raise ValueError("Server-side input token validation differs from baseline")
    validate_single_serving_change(baseline_manifest, cpu8_manifest)

    for name, (rows, manifest) in variants.items():
        if manifest.get("status") != "completed":
            raise ValueError(f"Run {name} is not completed")
        phases = {
            int(phase["concurrency"]): phase for phase in manifest.get("phases", [])
        }
        for row in rows:
            concurrency = row["concurrency"]
            if int(row["requests"]) != 100 or int(row["successes"]) != 100:
                raise ValueError(f"Incomplete phase for {name} C={concurrency}")
            if int(finite(row["total_prompt_tokens"])) != int(
                finite(row["server_prompt_tokens_delta"])
            ):
                raise ValueError(f"Prompt token mismatch for {name} C={concurrency}")
            if int(finite(row["total_completion_tokens"])) != int(
                finite(row["server_generation_tokens_delta"])
            ):
                raise ValueError(f"Generation token mismatch for {name} C={concurrency}")
            phase = phases.get(int(concurrency))
            if phase is None:
                raise ValueError(f"Missing phase metadata for {name} C={concurrency}")
            wall_seconds = (
                datetime.fromisoformat(phase["finished_at_utc"])
                - datetime.fromisoformat(phase["started_at_utc"])
            ).total_seconds()
            timer_gap = abs(wall_seconds - finite(phase["duration_seconds"]))
            if timer_gap > max(5.0, finite(phase["duration_seconds"]) * 0.01):
                raise ValueError(
                    f"Host interruption detected for {name} C={concurrency}: "
                    f"wall/timer gap={timer_gap:.2f}s"
                )
            if phase.get("metrics_scrape_errors"):
                raise ValueError(f"Metric scrape failed for {name} C={concurrency}")
    return concurrencies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("benchmark/results"))
    parser.add_argument(
        "--output", type=Path, default=Path("benchmark/results/comparison-cpu8")
    )
    args = parser.parse_args()

    variants = {name: load_variant(args.results_root / name) for name in VARIANTS}
    concurrencies = validate(variants)
    args.output.mkdir(parents=True, exist_ok=True)
    charts_dir = args.output / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    by_variant = {
        name: {int(row["concurrency"]): row for row in rows}
        for name, (rows, _manifest) in variants.items()
    }

    comparison_rows: list[dict[str, Any]] = []
    for concurrency in concurrencies:
        baseline = by_variant["baseline"][concurrency]
        cpu8 = by_variant["baseline-cpu8"][concurrency]
        comparison_rows.append(
            {
                "concurrency": concurrency,
                "baseline_output_tps": fmt(baseline["output_token_throughput_tps"], 6),
                "cpu8_output_tps": fmt(cpu8["output_token_throughput_tps"], 6),
                "output_change_percent": fmt(
                    percent_change(
                        baseline["output_token_throughput_tps"],
                        cpu8["output_token_throughput_tps"],
                    ),
                    6,
                ),
                "baseline_e2e_p95_seconds": fmt(baseline["e2e_seconds_p95"], 6),
                "cpu8_e2e_p95_seconds": fmt(cpu8["e2e_seconds_p95"], 6),
                "e2e_p95_change_percent": fmt(
                    percent_change(baseline["e2e_seconds_p95"], cpu8["e2e_seconds_p95"]),
                    6,
                ),
                "baseline_ttft_p95_seconds": fmt(baseline["ttft_seconds_p95"], 6),
                "cpu8_ttft_p95_seconds": fmt(cpu8["ttft_seconds_p95"], 6),
                "ttft_p95_change_percent": fmt(
                    percent_change(baseline["ttft_seconds_p95"], cpu8["ttft_seconds_p95"]),
                    6,
                ),
                "baseline_tpot_p95_ms": fmt(baseline["tpot_seconds_p95"], 6),
                "cpu8_tpot_p95_ms": fmt(cpu8["tpot_seconds_p95"], 6),
                "tpot_p95_change_percent": fmt(
                    percent_change(baseline["tpot_seconds_p95"], cpu8["tpot_seconds_p95"]),
                    6,
                ),
                "baseline_avg_cpu_cores": fmt(baseline["avg_pod_cpu_cores"], 6),
                "cpu8_avg_cpu_cores": fmt(cpu8["avg_pod_cpu_cores"], 6),
                "baseline_peak_running": fmt(baseline["peak_running_requests"], 0),
                "cpu8_peak_running": fmt(cpu8["peak_running_requests"], 0),
                "baseline_peak_waiting": fmt(baseline["peak_waiting_requests"], 0),
                "cpu8_peak_waiting": fmt(cpu8["peak_waiting_requests"], 0),
                "baseline_peak_kv_percent": fmt(baseline["peak_kv_cache_percent"], 6),
                "cpu8_peak_kv_percent": fmt(cpu8["peak_kv_cache_percent"], 6),
                "baseline_peak_memory_gib": fmt(baseline["peak_pod_memory_gib"], 6),
                "cpu8_peak_memory_gib": fmt(cpu8["peak_pod_memory_gib"], 6),
            }
        )
    write_csv(args.output / "comparison.csv", comparison_rows)

    chart_specs = (
        ("output-token-throughput.svg", "Output token throughput", "token/s", "output_token_throughput_tps"),
        ("e2e-p95.svg", "E2E latency p95", "seconds", "e2e_seconds_p95"),
        ("ttft-p95.svg", "TTFT p95", "seconds", "ttft_seconds_p95"),
        ("tpot-p95.svg", "TPOT p95", "milliseconds/token", "tpot_seconds_p95"),
        ("pod-cpu.svg", "Average Pod CPU", "cores", "avg_pod_cpu_cores"),
        ("peak-running.svg", "Peak running requests", "requests", "peak_running_requests"),
        ("peak-waiting.svg", "Peak waiting requests", "requests", "peak_waiting_requests"),
        ("kv-cache.svg", "Peak KV cache usage", "percent", "peak_kv_cache_percent"),
        ("pod-memory.svg", "Peak Pod memory", "GiB", "peak_pod_memory_gib"),
    )
    for filename, title, unit, metric in chart_specs:
        series = [
            (
                DISPLAY_NAMES[name],
                [finite(by_variant[name][concurrency][metric]) for concurrency in concurrencies],
            )
            for name in VARIANTS
        ]
        line_chart(charts_dir / filename, title, concurrencies, series, unit)

    table = [
        "| C | Output tok/s 6 → 8 | 변화 | E2E p95 6 → 8 | 변화 | TPOT p95 6 → 8 | 변화 | Avg CPU 6 → 8 | Peak run/wait 6 → 8 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison_rows:
        table.append(
            f"| {row['concurrency']} | {float(row['baseline_output_tps']):.2f} → {float(row['cpu8_output_tps']):.2f} | "
            f"{float(row['output_change_percent']):+.1f}% | {float(row['baseline_e2e_p95_seconds']):.2f}s → {float(row['cpu8_e2e_p95_seconds']):.2f}s | "
            f"{float(row['e2e_p95_change_percent']):+.1f}% | {float(row['baseline_tpot_p95_ms']):.2f}ms → {float(row['cpu8_tpot_p95_ms']):.2f}ms | "
            f"{float(row['tpot_p95_change_percent']):+.1f}% | {float(row['baseline_avg_cpu_cores']):.2f} → {float(row['cpu8_avg_cpu_cores']):.2f} | "
            f"{row['baseline_peak_running']}/{row['baseline_peak_waiting']} → {row['cpu8_peak_running']}/{row['cpu8_peak_waiting']} |"
        )

    total_requests = sum(
        int(row["requests"]) for name in VARIANTS for row in by_variant[name].values()
    )
    total_failures = sum(
        int(row["failures"]) for name in VARIANTS for row in by_variant[name].values()
    )
    total_oom = sum(
        finite(row["oom_kill_events_delta"])
        for name in VARIANTS
        for row in by_variant[name].values()
    )
    excluded_phases = [
        (name, phase)
        for name, (_rows, manifest) in variants.items()
        for phase in manifest.get("excluded_phases", [])
    ]
    excluded_text = (
        ", ".join(
            f"{name} C={int(phase['concurrency'])}"
            for name, phase in excluded_phases
        )
        if excluded_phases
        else "없음"
    )
    report = f"""# Baseline CPU limit 6 vs 8 자동 비교

## 검증

- 비교 요청: `{total_requests}`건, 실패 `{total_failures}`건
- prompt SHA-256, 모델, image args, memory, CPU request, KV, scheduler, sampling과 workload가 동일함
- 유일한 serving 변경은 container CPU limit `6 → 8`
- client/server prompt와 generation token counter가 모든 단계에서 일치함
- 정식 phase의 UTC wall clock과 monotonic timer 오차가 1%/5초 이내이며 metric scrape error가 없음
- host 중단 표본은 원본 보존 후 제외·재측정함: `{excluded_text}`
- 전체 OOM kill 증가량: `{total_oom:.0f}`

## 결과

{chr(10).join(table)}

## 그래프

- [Output throughput](charts/output-token-throughput.svg)
- [E2E p95](charts/e2e-p95.svg)
- [TTFT p95](charts/ttft-p95.svg)
- [TPOT p95](charts/tpot-p95.svg)
- [Pod CPU](charts/pod-cpu.svg)
- [Peak running](charts/peak-running.svg)
- [Peak waiting](charts/peak-waiting.svg)
- [KV cache](charts/kv-cache.svg)
- [Pod memory](charts/pod-memory.svg)

이 문서는 원시 summary에서 자동 생성한 사실표다. 원인과 최종 권고는 [CPU8 분석 리포트](../../../reports/05_BASELINE_CPU8_ANALYSIS.md)에 정리한다.
"""
    (args.output / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"Validated the one-field CPU change across {total_requests} requests")


if __name__ == "__main__":
    main()
