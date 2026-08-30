# 전체 CPU serving variant 종합 비교

## 검증

- 필수 variant `8`개, variant별 `700`건, 총 `5,600`건을 검증했다.
- 모든 run은 동일 prompt SHA-256, tokenized input, 모델, vLLM, workload config와 동시성 `1, 2, 5, 10, 20, 50, 100`을 사용한다.
- 각 phase는 `100/100` 성공, client/server prompt·generation token 합계 일치, metric scrape error 0, wall/monotonic timer 허용 오차 통과 조건을 만족한다.
- 모든 phase의 OOM/OOM-kill은 `0`이다. cgroup `memory.events:max` 접촉은 `baseline-cpu8` C=5 +2에서 관찰됐으며 메모리 압박 신호로 별도 보고한다.
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
| 1 | `baseline` | 16.58 | +0.0% | — | — | 4.66s | 1/0 |
| 1 | `baseline-cpu8` | 22.02 | +32.8% | — | — | 3.60s | 1/0 |
| 1 | `mtp` | 22.42 | +35.2% | `baseline` | +35.2% | 3.84s | 1/0 |
| 1 | `mtp-cpu8` | 30.22 | +82.3% | `baseline-cpu8` | +37.2% | 2.94s | 1/0 |
| 1 | `mtp-kv-tuned` | 22.79 | +37.5% | `mtp` | +1.6% | 3.78s | 1/0 |
| 1 | `mtp-kv-tuned-cpu8` | 30.49 | +83.9% | `mtp-cpu8` | +0.9% | 2.89s | 1/0 |
| 1 | `mtp-kv768-cpu8` | 30.27 | +82.6% | `mtp-cpu8` | +0.2% | 2.88s | 1/0 |
| 1 | `mtp-seq24-cpu8` | 30.10 | +81.6% | `mtp-cpu8` | -0.4% | 2.93s | 1/0 |
| 2 | `baseline` | 28.56 | +0.0% | — | — | 5.14s | 2/0 |
| 2 | `baseline-cpu8` | 38.73 | +35.6% | — | — | 3.84s | 2/0 |
| 2 | `mtp` | 35.25 | +23.4% | `baseline` | +23.4% | 4.94s | 2/0 |
| 2 | `mtp-cpu8` | 47.46 | +66.2% | `baseline-cpu8` | +22.5% | 3.75s | 2/0 |
| 2 | `mtp-kv-tuned` | 35.42 | +24.0% | `mtp` | +0.5% | 4.96s | 2/0 |
| 2 | `mtp-kv-tuned-cpu8` | 47.61 | +66.7% | `mtp-cpu8` | +0.3% | 3.69s | 2/0 |
| 2 | `mtp-kv768-cpu8` | 46.88 | +64.2% | `mtp-cpu8` | -1.2% | 3.81s | 2/0 |
| 2 | `mtp-seq24-cpu8` | 47.34 | +65.8% | `mtp-cpu8` | -0.2% | 3.79s | 2/0 |
| 5 | `baseline` | 52.88 | +0.0% | — | — | 7.14s | 5/0 |
| 5 | `baseline-cpu8` | 68.56 | +29.7% | — | — | 5.58s | 5/0 |
| 5 | `mtp` | 53.85 | +1.8% | `baseline` | +1.8% | 7.55s | 5/0 |
| 5 | `mtp-cpu8` | 70.83 | +34.0% | `baseline-cpu8` | +3.3% | 5.87s | 5/0 |
| 5 | `mtp-kv-tuned` | 54.51 | +3.1% | `mtp` | +1.2% | 7.56s | 5/0 |
| 5 | `mtp-kv-tuned-cpu8` | 71.73 | +35.6% | `mtp-cpu8` | +1.3% | 5.88s | 5/0 |
| 5 | `mtp-kv768-cpu8` | 71.58 | +35.4% | `mtp-cpu8` | +1.1% | 5.82s | 5/0 |
| 5 | `mtp-seq24-cpu8` | 70.91 | +34.1% | `mtp-cpu8` | +0.1% | 5.79s | 5/0 |
| 10 | `baseline` | 70.01 | +0.0% | — | — | 10.19s | 10/1 |
| 10 | `baseline-cpu8` | 93.79 | +34.0% | — | — | 7.68s | 10/1 |
| 10 | `mtp` | 54.55 | -22.1% | `baseline` | -22.1% | 13.26s | 5/5 |
| 10 | `mtp-cpu8` | 71.41 | +2.0% | `baseline-cpu8` | -23.9% | 10.19s | 5/5 |
| 10 | `mtp-kv-tuned` | 62.13 | -11.3% | `mtp` | +13.9% | 13.06s | 8/2 |
| 10 | `mtp-kv-tuned-cpu8` | 80.10 | +14.4% | `mtp-cpu8` | +12.2% | 9.90s | 8/2 |
| 10 | `mtp-kv768-cpu8` | 80.04 | +14.3% | `mtp-cpu8` | +12.1% | 9.67s | 8/2 |
| 10 | `mtp-seq24-cpu8` | 72.82 | +4.0% | `mtp-cpu8` | +2.0% | 10.02s | 5/5 |
| 20 | `baseline` | 80.19 | +0.0% | — | — | 22.29s | 16/11 |
| 20 | `baseline-cpu8` | 103.93 | +29.6% | — | — | 17.31s | 16/11 |
| 20 | `mtp` | 53.71 | -33.0% | `baseline` | -33.0% | 25.42s | 5/15 |
| 20 | `mtp-cpu8` | 72.13 | -10.1% | `baseline-cpu8` | -30.6% | 18.99s | 5/15 |
| 20 | `mtp-kv-tuned` | 62.34 | -22.3% | `mtp` | +16.1% | 22.74s | 8/12 |
| 20 | `mtp-kv-tuned-cpu8` | 81.81 | +2.0% | `mtp-cpu8` | +13.4% | 17.53s | 8/12 |
| 20 | `mtp-kv768-cpu8` | 80.52 | +0.4% | `mtp-cpu8` | +11.6% | 18.20s | 8/12 |
| 20 | `mtp-seq24-cpu8` | 72.41 | -9.7% | `mtp-cpu8` | +0.4% | 19.06s | 5/15 |
| 50 | `baseline` | 79.91 | +0.0% | — | — | 43.02s | 16/41 |
| 50 | `baseline-cpu8` | 102.40 | +28.2% | — | — | 35.18s | 16/39 |
| 50 | `mtp` | 54.81 | -31.4% | `baseline` | -31.4% | 59.29s | 5/45 |
| 50 | `mtp-cpu8` | 71.75 | -10.2% | `baseline-cpu8` | -29.9% | 45.32s | 5/45 |
| 50 | `mtp-kv-tuned` | 62.32 | -22.0% | `mtp` | +13.7% | 53.08s | 8/42 |
| 50 | `mtp-kv-tuned-cpu8` | 82.04 | +2.7% | `mtp-cpu8` | +14.3% | 40.08s | 8/42 |
| 50 | `mtp-kv768-cpu8` | 81.36 | +1.8% | `mtp-cpu8` | +13.4% | 40.61s | 8/42 |
| 50 | `mtp-seq24-cpu8` | 72.79 | -8.9% | `mtp-cpu8` | +1.4% | 44.36s | 5/45 |
| 100 | `baseline` | 81.40 | +0.0% | — | — | 74.64s | 16/90 |
| 100 | `baseline-cpu8` | 104.06 | +27.8% | — | — | 58.52s | 16/90 |
| 100 | `mtp` | 55.06 | -32.4% | `baseline` | -32.4% | 111.75s | 5/95 |
| 100 | `mtp-cpu8` | 71.22 | -12.5% | `baseline-cpu8` | -31.6% | 87.42s | 5/95 |
| 100 | `mtp-kv-tuned` | 62.27 | -23.5% | `mtp` | +13.1% | 99.14s | 8/92 |
| 100 | `mtp-kv-tuned-cpu8` | 81.51 | +0.1% | `mtp-cpu8` | +14.4% | 76.61s | 8/92 |
| 100 | `mtp-kv768-cpu8` | 81.94 | +0.7% | `mtp-cpu8` | +15.1% | 76.44s | 8/92 |
| 100 | `mtp-seq24-cpu8` | 72.72 | -10.7% | `mtp-cpu8` | +2.1% | 84.68s | 5/95 |

## 그래프

- [전체 output throughput](charts/output-throughput.svg)
- [핵심 단일 변수 비교](charts/core-throughput.svg)
- [CPU6 baseline 대비 변화율](charts/vs-cpu6-baseline.svg)
- [같은 CPU의 직전 단독/증분 효과](charts/same-cpu-direct-effect.svg)
- [동시성별 peak KV cache 점유](charts/kv-cache-growth-by-concurrency.svg)
- [KV cache capacity–performance trade-off (C=20)](charts/kv-cache-tradeoff-c20.svg)

원시 값과 전체 지표는 [comparison.csv](comparison.csv)에 저장한다. 단일 실행 간 host background load와 thermal 변동은 제거되지 않으므로 작은 차이는 반복 실험 없이 확정값으로 해석하지 않는다.
