# 전체 CPU serving variant 종합 비교

## 검증

- 필수 variant `8`개, variant별 `700`건, 총 `5,600`건을 검증했다.
- 모든 run은 동일 prompt SHA-256, tokenized input, 모델, vLLM, workload config와 동시성 `1, 2, 5, 10, 20, 50, 100`을 사용한다.
- 각 phase는 `100/100` 성공, client/server prompt·generation token 합계 일치, metric scrape error와 OOM kill 0, wall/monotonic timer 허용 오차 통과 조건을 만족한다.
- captured image, env, container args와 CPU/memory resources를 아래 factor matrix의 기대값과 정확히 대조했다.

`mtp-kv-tuned`와 `mtp-kv-tuned-cpu8`은 보존된 역사적 artifact ID다. 두 설정은 KV `512→768MiB`와 `max-num-seqs 20→24`를 동시에 변경한 **legacy capacity bundle**이며 KV-only 최적화로 해석하지 않는다.

## Factor matrix

| Artifact ID | 표시명 | CPU | MTP2 | KV | max-num-seqs | 분류 |
|---|---|---:|---|---:|---:|---|
| `baseline` | CPU6 baseline | 6 | off | 512MiB | 20 | reference |
| `baseline-cpu8` | CPU8 baseline | 8 | off | 512MiB | 20 | CPU limit 6→8 (reported in CPU6-baseline column) |
| `mtp` | CPU6 MTP2 | 6 | on | 512MiB | 20 | MTP2 only |
| `mtp-cpu8` | CPU8 MTP2 | 8 | on | 512MiB | 20 | MTP2 only |
| `mtp-kv-tuned` | CPU6 MTP2 + legacy capacity bundle | 6 | on | 768MiB | 24 | legacy capacity bundle; KV-only 아님 |
| `mtp-kv-tuned-cpu8` | CPU8 MTP2 + legacy capacity bundle | 8 | on | 768MiB | 24 | legacy capacity bundle; KV-only 아님 |
| `mtp-kv768-cpu8` | CPU8 MTP2 + KV768 only | 8 | on | 768MiB | 20 | KV 512→768MiB only |
| `mtp-seq24-cpu8` | CPU8 MTP2 + maxseq24 only | 8 | on | 512MiB | 24 | max-num-seqs 20→24 only |

## 동시성별 실측

`vs CPU6 baseline`은 같은 동시성의 `baseline` 대비 값이다. `direct effect`는 CPU를 고정한 직전 reference 대비 값이므로 MTP, KV-only, maxseq-only 및 legacy bundle의 증분 효과를 나타낸다. `baseline-cpu8`의 CPU 변경 효과는 `vs CPU6 baseline` 열에서 확인한다.

`run/wait`는 각 metric 시계열에서 독립적으로 구한 peak running / peak waiting이며, 같은 시점의 합으로 해석하지 않는다.

| C | Variant | output tok/s | vs CPU6 baseline | same-CPU reference | direct effect | E2E p95 | run/wait |
|---:|---|---:|---:|---|---:|---:|---:|
| 1 | `baseline` | 5.16 | +0.0% | — | — | 19.00s | 1/0 |
| 1 | `baseline-cpu8` | 6.44 | +24.8% | — | — | 15.61s | 1/0 |
| 1 | `mtp` | 7.80 | +51.1% | `baseline` | +51.1% | 14.46s | 1/0 |
| 1 | `mtp-cpu8` | 8.24 | +59.6% | `baseline-cpu8` | +27.8% | 13.35s | 1/0 |
| 1 | `mtp-kv-tuned` | 7.43 | +44.0% | `mtp` | -4.7% | 15.36s | 1/0 |
| 1 | `mtp-kv-tuned-cpu8` | 9.33 | +80.8% | `mtp-cpu8` | +13.3% | 12.28s | 1/0 |
| 1 | `mtp-kv768-cpu8` | 8.13 | +57.5% | `mtp-cpu8` | -1.3% | 13.21s | 1/0 |
| 1 | `mtp-seq24-cpu8` | 8.97 | +73.7% | `mtp-cpu8` | +8.9% | 12.39s | 1/0 |
| 2 | `baseline` | 7.64 | +0.0% | — | — | 22.32s | 2/0 |
| 2 | `baseline-cpu8` | 9.28 | +21.4% | — | — | 18.54s | 2/0 |
| 2 | `mtp` | 9.99 | +30.7% | `baseline` | +30.7% | 19.50s | 2/0 |
| 2 | `mtp-cpu8` | 10.30 | +34.8% | `baseline-cpu8` | +11.0% | 18.42s | 2/0 |
| 2 | `mtp-kv-tuned` | 10.01 | +31.0% | `mtp` | +0.2% | 19.25s | 2/0 |
| 2 | `mtp-kv-tuned-cpu8` | 12.10 | +58.3% | `mtp-cpu8` | +17.4% | 15.94s | 2/0 |
| 2 | `mtp-kv768-cpu8` | 10.63 | +39.1% | `mtp-cpu8` | +3.2% | 17.22s | 2/0 |
| 2 | `mtp-seq24-cpu8` | 12.04 | +57.5% | `mtp-cpu8` | +16.8% | 15.91s | 2/0 |
| 5 | `baseline` | 11.28 | +0.0% | — | — | 38.92s | 5/0 |
| 5 | `baseline-cpu8` | 13.16 | +16.7% | — | — | 34.32s | 5/0 |
| 5 | `mtp` | 11.87 | +5.3% | `baseline` | +5.3% | 37.32s | 5/0 |
| 5 | `mtp-cpu8` | 14.38 | +27.6% | `baseline-cpu8` | +9.3% | 30.22s | 5/0 |
| 5 | `mtp-kv-tuned` | 11.40 | +1.1% | `mtp` | -3.9% | 37.73s | 5/0 |
| 5 | `mtp-kv-tuned-cpu8` | 14.35 | +27.2% | `mtp-cpu8` | -0.3% | 30.35s | 5/0 |
| 5 | `mtp-kv768-cpu8` | 12.39 | +9.9% | `mtp-cpu8` | -13.8% | 34.85s | 5/0 |
| 5 | `mtp-seq24-cpu8` | 14.30 | +26.8% | `mtp-cpu8` | -0.6% | 30.81s | 5/0 |
| 10 | `baseline` | 12.06 | +0.0% | — | — | 66.80s | 10/1 |
| 10 | `baseline-cpu8` | 14.94 | +23.9% | — | — | 53.92s | 10/1 |
| 10 | `mtp` | 11.81 | -2.1% | `baseline` | -2.1% | 63.28s | 5/5 |
| 10 | `mtp-cpu8` | 14.41 | +19.5% | `baseline-cpu8` | -3.5% | 52.75s | 5/5 |
| 10 | `mtp-kv-tuned` | 11.51 | -4.6% | `mtp` | -2.6% | 71.46s | 8/2 |
| 10 | `mtp-kv-tuned-cpu8` | 14.83 | +23.0% | `mtp-cpu8` | +2.9% | 55.39s | 8/2 |
| 10 | `mtp-kv768-cpu8` | 12.95 | +7.4% | `mtp-cpu8` | -10.2% | 60.17s | 8/2 |
| 10 | `mtp-seq24-cpu8` | 14.36 | +19.1% | `mtp-cpu8` | -0.4% | 53.27s | 5/5 |
| 20 | `baseline` | 13.50 | +0.0% | — | — | 131.17s | 16/11 |
| 20 | `baseline-cpu8` | 16.22 | +20.2% | — | — | 109.94s | 16/9 |
| 20 | `mtp` | 11.78 | -12.7% | `baseline` | -12.7% | 114.00s | 5/15 |
| 20 | `mtp-cpu8` | 14.62 | +8.3% | `baseline-cpu8` | -9.9% | 93.47s | 5/15 |
| 20 | `mtp-kv-tuned` | 11.84 | -12.3% | `mtp` | +0.5% | 127.53s | 8/12 |
| 20 | `mtp-kv-tuned-cpu8` | 14.75 | +9.3% | `mtp-cpu8` | +0.9% | 100.32s | 8/12 |
| 20 | `mtp-kv768-cpu8` | 13.10 | -3.0% | `mtp-cpu8` | -10.4% | 114.02s | 8/12 |
| 20 | `mtp-seq24-cpu8` | 14.40 | +6.6% | `mtp-cpu8` | -1.5% | 96.26s | 5/15 |
| 50 | `baseline` | 13.46 | +0.0% | — | — | 254.46s | 16/40 |
| 50 | `baseline-cpu8` | 15.03 | +11.7% | — | — | 230.02s | 16/41 |
| 50 | `mtp` | 12.31 | -8.6% | `baseline` | -8.6% | 276.43s | 5/45 |
| 50 | `mtp-cpu8` | 14.89 | +10.6% | `baseline-cpu8` | -0.9% | 219.23s | 5/45 |
| 50 | `mtp-kv-tuned` | 12.52 | -7.0% | `mtp` | +1.7% | 261.42s | 8/42 |
| 50 | `mtp-kv-tuned-cpu8` | 14.33 | +6.5% | `mtp-cpu8` | -3.7% | 228.51s | 8/42 |
| 50 | `mtp-kv768-cpu8` | 14.35 | +6.6% | `mtp-cpu8` | -3.6% | 234.23s | 8/42 |
| 50 | `mtp-seq24-cpu8` | 14.46 | +7.4% | `mtp-cpu8` | -2.9% | 226.52s | 5/45 |
| 100 | `baseline` | 13.54 | +0.0% | — | — | 464.06s | 16/91 |
| 100 | `baseline-cpu8` | 15.15 | +11.8% | — | — | 415.57s | 16/91 |
| 100 | `mtp` | 12.05 | -11.0% | `baseline` | -11.0% | 522.12s | 5/95 |
| 100 | `mtp-cpu8` | 15.18 | +12.0% | `baseline-cpu8` | +0.2% | 415.08s | 5/95 |
| 100 | `mtp-kv-tuned` | 12.29 | -9.2% | `mtp` | +2.0% | 510.03s | 8/92 |
| 100 | `mtp-kv-tuned-cpu8` | 13.66 | +0.9% | `mtp-cpu8` | -10.0% | 463.65s | 8/92 |
| 100 | `mtp-kv768-cpu8` | 14.85 | +9.7% | `mtp-cpu8` | -2.1% | 425.92s | 8/92 |
| 100 | `mtp-seq24-cpu8` | 14.35 | +6.0% | `mtp-cpu8` | -5.4% | 437.33s | 5/95 |

## 그래프

- [전체 output throughput](charts/output-throughput.svg)
- [핵심 단일 변수 비교](charts/core-throughput.svg)
- [CPU6 baseline 대비 변화율](charts/vs-cpu6-baseline.svg)
- [같은 CPU의 직전 단독/증분 효과](charts/same-cpu-direct-effect.svg)
- [KV cache capacity–performance trade-off (C=20)](charts/kv-cache-tradeoff-c20.svg)

원시 값과 전체 지표는 [comparison.csv](comparison.csv)에 저장한다. 단일 실행 간 host background load와 thermal 변동은 제거되지 않으므로 작은 차이는 반복 실험 없이 확정값으로 해석하지 않는다.
