#!/usr/bin/env python3
"""Validate CPU-8 baseline, MTP, and MTP capacity-bundle benchmark results."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from analyze import line_chart
from compare import finite, fmt, load_variant, percent_change, write_csv


VARIANTS = ("baseline-cpu8", "mtp-cpu8", "mtp-kv-tuned-cpu8")
DISPLAY_NAMES = {
    "baseline-cpu8": "CPU8 baseline",
    "mtp-cpu8": "CPU8 MTP2",
    "mtp-kv-tuned-cpu8": "CPU8 MTP2 + KV768 + max-seqs24",
}
MTP_CONFIG = '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'


def without_experiment(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized.pop("experiment", None)
    return normalized


def replace_arg(args: list[str], flag: str, value: str) -> list[str]:
    updated = copy.deepcopy(args)
    try:
        value_index = updated.index(flag) + 1
    except ValueError as exc:
        raise ValueError(f"Missing expected container argument {flag}") from exc
    if value_index >= len(updated):
        raise ValueError(f"Container argument {flag} has no value")
    updated[value_index] = value
    return updated


def validate_container_changes(manifests: dict[str, dict]) -> None:
    containers = {
        name: copy.deepcopy(manifest["environment"]["kubernetes"]["container"])
        for name, manifest in manifests.items()
    }
    baseline = containers["baseline-cpu8"]
    mtp = containers["mtp-cpu8"]
    combined = containers["mtp-kv-tuned-cpu8"]

    for name, container in containers.items():
        cpu_limit = str(container["resources"]["limits"].get("cpu"))
        if cpu_limit != "8":
            raise ValueError(f"Expected CPU limit 8 for {name}, found {cpu_limit!r}")
        if container["image"] != baseline["image"]:
            raise ValueError(f"Image changed for {name}")
        if container["env"] != baseline["env"]:
            raise ValueError(f"Environment changed for {name}")
        if container["resources"] != baseline["resources"]:
            raise ValueError(f"Resources changed for {name}")

    expected_mtp_args = baseline["args"] + ["--speculative-config", MTP_CONFIG]
    if mtp["args"] != expected_mtp_args:
        raise ValueError("MTP CPU8 args differ from baseline by more than MTP config")

    expected_combined_args = replace_arg(expected_mtp_args, "--max-num-seqs", "24")
    expected_combined_args = replace_arg(
        expected_combined_args, "--kv-cache-memory-bytes", "805306368"
    )
    if combined["args"] != expected_combined_args:
        raise ValueError(
            "CPU8 capacity-bundle args differ from MTP by more than "
            "max sequences 24 and KV 768MiB"
        )


def validate(variants: dict[str, tuple[list[dict], dict]]) -> list[int]:
    baseline_rows, baseline_manifest = variants["baseline-cpu8"]
    concurrencies = [int(row["concurrency"]) for row in baseline_rows]
    baseline_config = without_experiment(baseline_manifest["config"])
    prompt_hash = baseline_manifest["prompts_sha256"]
    input_validation = baseline_manifest["input_token_validation"]
    baseline_tokens = {
        int(row["concurrency"]): (
            int(finite(row["total_prompt_tokens"])),
            int(finite(row["total_completion_tokens"])),
        )
        for row in baseline_rows
    }
    manifests = {name: manifest for name, (_rows, manifest) in variants.items()}
    validate_container_changes(manifests)

    for name, (rows, manifest) in variants.items():
        if manifest.get("status") != "completed":
            raise ValueError(f"Run {name} is not completed")
        if [int(row["concurrency"]) for row in rows] != concurrencies:
            raise ValueError(f"Concurrency matrix differs for {name}")
        if without_experiment(manifest["config"]) != baseline_config:
            raise ValueError(f"Benchmark config differs for {name}")
        if manifest["prompts_sha256"] != prompt_hash:
            raise ValueError(f"Prompt SHA-256 differs for {name}")
        if manifest["input_token_validation"] != input_validation:
            raise ValueError(f"Input token validation differs for {name}")

        phases = {
            int(phase["concurrency"]): phase for phase in manifest.get("phases", [])
        }
        for row in rows:
            concurrency = int(row["concurrency"])
            if (
                int(row["requests"]) != 100
                or int(row["successes"]) != 100
                or int(row["failures"]) != 0
            ):
                raise ValueError(f"Incomplete phase for {name} C={concurrency}")
            row_tokens = (
                int(finite(row["total_prompt_tokens"])),
                int(finite(row["total_completion_tokens"])),
            )
            if row_tokens != baseline_tokens[concurrency]:
                raise ValueError(f"Cross-variant token totals differ for {name} C={concurrency}")
            if int(finite(row["total_prompt_tokens"])) != int(
                finite(row["server_prompt_tokens_delta"])
            ):
                raise ValueError(f"Prompt token mismatch for {name} C={concurrency}")
            if int(finite(row["total_completion_tokens"])) != int(
                finite(row["server_generation_tokens_delta"])
            ):
                raise ValueError(f"Generation token mismatch for {name} C={concurrency}")
            phase = phases.get(concurrency)
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
        "--output",
        type=Path,
        default=Path("benchmark/results/comparison-cpu8-optimizations"),
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
        baseline = by_variant["baseline-cpu8"][concurrency]
        mtp = by_variant["mtp-cpu8"][concurrency]
        combined = by_variant["mtp-kv-tuned-cpu8"][concurrency]
        comparison_rows.append(
            {
                "concurrency": concurrency,
                "baseline_output_tps": fmt(baseline["output_token_throughput_tps"], 6),
                "mtp_output_tps": fmt(mtp["output_token_throughput_tps"], 6),
                "combined_output_tps": fmt(combined["output_token_throughput_tps"], 6),
                "mtp_vs_baseline_output_percent": fmt(
                    percent_change(
                        baseline["output_token_throughput_tps"],
                        mtp["output_token_throughput_tps"],
                    ),
                    6,
                ),
                "combined_vs_baseline_output_percent": fmt(
                    percent_change(
                        baseline["output_token_throughput_tps"],
                        combined["output_token_throughput_tps"],
                    ),
                    6,
                ),
                "capacity_bundle_vs_mtp_output_percent": fmt(
                    percent_change(
                        mtp["output_token_throughput_tps"],
                        combined["output_token_throughput_tps"],
                    ),
                    6,
                ),
                "baseline_e2e_p95_seconds": fmt(baseline["e2e_seconds_p95"], 6),
                "mtp_e2e_p95_seconds": fmt(mtp["e2e_seconds_p95"], 6),
                "combined_e2e_p95_seconds": fmt(combined["e2e_seconds_p95"], 6),
                "combined_vs_baseline_e2e_percent": fmt(
                    percent_change(
                        baseline["e2e_seconds_p95"], combined["e2e_seconds_p95"]
                    ),
                    6,
                ),
                "baseline_ttft_p95_seconds": fmt(baseline["ttft_seconds_p95"], 6),
                "mtp_ttft_p95_seconds": fmt(mtp["ttft_seconds_p95"], 6),
                "combined_ttft_p95_seconds": fmt(combined["ttft_seconds_p95"], 6),
                "baseline_tpot_p95_ms": fmt(baseline["tpot_ms_p95"], 6),
                "mtp_tpot_p95_ms": fmt(mtp["tpot_ms_p95"], 6),
                "combined_tpot_p95_ms": fmt(combined["tpot_ms_p95"], 6),
                "baseline_peak_running": fmt(baseline["peak_running_requests"], 0),
                "mtp_peak_running": fmt(mtp["peak_running_requests"], 0),
                "combined_peak_running": fmt(combined["peak_running_requests"], 0),
                "baseline_peak_waiting": fmt(baseline["peak_waiting_requests"], 0),
                "mtp_peak_waiting": fmt(mtp["peak_waiting_requests"], 0),
                "combined_peak_waiting": fmt(combined["peak_waiting_requests"], 0),
                "baseline_peak_kv_percent": fmt(baseline["peak_kv_cache_percent"], 6),
                "mtp_peak_kv_percent": fmt(mtp["peak_kv_cache_percent"], 6),
                "combined_peak_kv_percent": fmt(combined["peak_kv_cache_percent"], 6),
                "baseline_avg_cpu": fmt(baseline["avg_pod_cpu_cores"], 6),
                "mtp_avg_cpu": fmt(mtp["avg_pod_cpu_cores"], 6),
                "combined_avg_cpu": fmt(combined["avg_pod_cpu_cores"], 6),
                "baseline_peak_memory_gib": fmt(baseline["peak_pod_memory_gib"], 6),
                "mtp_peak_memory_gib": fmt(mtp["peak_pod_memory_gib"], 6),
                "combined_peak_memory_gib": fmt(combined["peak_pod_memory_gib"], 6),
                "mtp_acceptance_percent": fmt(mtp["spec_acceptance_percent"], 6),
                "combined_acceptance_percent": fmt(
                    combined["spec_acceptance_percent"], 6
                ),
            }
        )
    write_csv(args.output / "comparison.csv", comparison_rows)

    chart_specs = (
        ("output-token-throughput.svg", "CPU8 output token throughput", "token/s", "output_token_throughput_tps"),
        ("e2e-p95.svg", "CPU8 E2E latency p95", "seconds", "e2e_seconds_p95"),
        ("ttft-p95.svg", "CPU8 TTFT p95", "seconds", "ttft_seconds_p95"),
        ("tpot-p95.svg", "CPU8 TPOT p95", "milliseconds/token", "tpot_ms_p95"),
        ("peak-running.svg", "CPU8 peak running requests", "requests", "peak_running_requests"),
        ("peak-waiting.svg", "CPU8 peak waiting requests", "requests", "peak_waiting_requests"),
        ("kv-cache.svg", "CPU8 peak KV cache usage", "percent", "peak_kv_cache_percent"),
        ("pod-memory.svg", "CPU8 peak Pod memory", "GiB", "peak_pod_memory_gib"),
        ("pod-cpu.svg", "CPU8 average Pod CPU", "cores", "avg_pod_cpu_cores"),
    )
    for filename, title, unit, metric in chart_specs:
        series = [
            (
                DISPLAY_NAMES[name],
                [finite(by_variant[name][c][metric]) for c in concurrencies],
            )
            for name in VARIANTS
        ]
        line_chart(charts_dir / filename, title, concurrencies, series, unit)
    line_chart(
        charts_dir / "mtp-acceptance.svg",
        "CPU8 MTP acceptance rate",
        concurrencies,
        [
            (
                DISPLAY_NAMES[name],
                [
                    finite(by_variant[name][c]["spec_acceptance_percent"])
                    for c in concurrencies
                ],
            )
            for name in ("mtp-cpu8", "mtp-kv-tuned-cpu8")
        ],
        "percent",
    )

    throughput_table = [
        "| C | Baseline | MTP2 | MTP2+KV768+seq24 | MTP vs base | Capacity bundle vs MTP | Bundle vs base |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    pressure_table = [
        "| C | E2E p95 base / MTP / bundle | Peak running base / MTP / bundle | Peak waiting base / MTP / bundle | Acceptance MTP / bundle |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in comparison_rows:
        baseline_output = f"{float(row['baseline_output_tps']):.2f}"
        if int(row["concurrency"]) == 5:
            baseline_output += "¹"
        throughput_table.append(
            f"| {row['concurrency']} | {baseline_output} | "
            f"{float(row['mtp_output_tps']):.2f} | {float(row['combined_output_tps']):.2f} | "
            f"{float(row['mtp_vs_baseline_output_percent']):+.1f}% | "
            f"{float(row['capacity_bundle_vs_mtp_output_percent']):+.1f}% | "
            f"{float(row['combined_vs_baseline_output_percent']):+.1f}% |"
        )
        pressure_table.append(
            f"| {row['concurrency']} | {float(row['baseline_e2e_p95_seconds']):.2f}s / "
            f"{float(row['mtp_e2e_p95_seconds']):.2f}s / "
            f"{float(row['combined_e2e_p95_seconds']):.2f}s | "
            f"{row['baseline_peak_running']}/{row['mtp_peak_running']}/"
            f"{row['combined_peak_running']} | "
            f"{row['baseline_peak_waiting']}/{row['mtp_peak_waiting']}/"
            f"{row['combined_peak_waiting']} | "
            f"{float(row['mtp_acceptance_percent']):.1f}% / {float(row['combined_acceptance_percent']):.1f}% |"
        )

    total_requests = sum(
        int(row["requests"])
        for name in VARIANTS
        for row in by_variant[name].values()
    )
    total_failures = sum(
        int(row["failures"])
        for name in VARIANTS
        for row in by_variant[name].values()
    )
    total_oom = sum(
        finite(row["oom_kill_events_delta"])
        for name in VARIANTS
        for row in by_variant[name].values()
    )
    report = f"""# CPU limit 8: Baseline vs MTP2 vs capacity bundle 자동 비교

## 검증

- 비교 요청: `{total_requests}`건, 실패 `{total_failures}`건
- 세 설정 모두 CPU request/limit `4/8`, 동일 image/model/memory/workload를 사용함
- 첫 단계는 MTP만 추가했고, 다음 단계는 KV `512→768MiB`와 max sequences `20→24`를 함께 추가함
- client/server token counter, wall/monotonic timer, metric scrape를 모든 phase에서 검증함
- 전체 OOM kill 증가량: `{total_oom:.0f}`

`mtp-kv-tuned-cpu8`은 역사적인 artifact ID다. 실제 의미는 `MTP2 + KV768MiB + max-seqs24` capacity bundle이며 KV 단독 실험이 아니다.

## 처리량

단위는 output token/s다.

{chr(10).join(throughput_table)}

## Latency와 scheduler

{chr(10).join(pressure_table)}

Peak running과 peak waiting은 각 시계열에서 독립적으로 구한 최댓값이며 같은 시점의 쌍이 아니다.

¹ C=5 baseline은 두 번째 유효 표본을 공식값으로 채택했으며 첫 유효 표본과 output throughput 차이는 19.5%였다.

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

이 문서는 원시 결과에서 자동 생성한 사실표다. 원인과 최종 권고는 [CPU8 MTP·capacity bundle 분석 리포트](../../../reports/06_CPU8_MTP_KV_ANALYSIS.md)에 정리한다.
"""
    (args.output / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"Validated CPU8 optimization comparison across {total_requests} requests")


if __name__ == "__main__":
    main()
