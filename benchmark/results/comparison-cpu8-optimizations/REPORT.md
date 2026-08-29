# CPU limit 8: Baseline vs MTP2 vs capacity bundle 자동 비교

## 검증

- 비교 요청: `2100`건, 실패 `0`건
- 세 설정 모두 CPU request/limit `4/8`, 동일 image/model/memory/workload를 사용함
- 첫 단계는 MTP만 추가했고, 다음 단계는 KV `512→768MiB`와 max sequences `20→24`를 함께 추가함
- client/server token counter, wall/monotonic timer, metric scrape를 모든 phase에서 검증함
- 전체 OOM kill 증가량: `0`

`mtp-kv-tuned-cpu8`은 역사적인 artifact ID다. 실제 의미는 `MTP2 + KV768MiB + max-seqs24` capacity bundle이며 KV 단독 실험이 아니다.

## 처리량

단위는 output token/s다.

| C | Baseline | MTP2 | MTP2+KV768+seq24 | MTP vs base | Capacity bundle vs MTP | Bundle vs base |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.44 | 8.24 | 9.33 | +27.8% | +13.3% | +44.8% |
| 2 | 9.28 | 10.30 | 12.10 | +11.0% | +17.4% | +30.4% |
| 5 | 13.16¹ | 14.38 | 14.35 | +9.3% | -0.3% | +9.0% |
| 10 | 14.94 | 14.41 | 14.83 | -3.5% | +2.9% | -0.8% |
| 20 | 16.22 | 14.62 | 14.75 | -9.9% | +0.9% | -9.0% |
| 50 | 15.03 | 14.89 | 14.33 | -0.9% | -3.7% | -4.6% |
| 100 | 15.15 | 15.18 | 13.66 | +0.2% | -10.0% | -9.8% |

## Latency와 scheduler

| C | E2E p95 base / MTP / bundle | Peak running base / MTP / bundle | Peak waiting base / MTP / bundle | Acceptance MTP / bundle |
|---:|---:|---:|---:|---:|
| 1 | 15.61s / 13.35s / 12.28s | 1/1/1 | 0/0/0 | 76.7% / 76.7% |
| 2 | 18.54s / 18.42s / 15.94s | 2/2/2 | 0/0/0 | 76.2% / 76.3% |
| 5 | 34.32s / 30.22s / 30.35s | 5/5/5 | 0/0/0 | 75.2% / 76.1% |
| 10 | 53.92s / 52.75s / 55.39s | 10/5/8 | 1/5/2 | 75.6% / 75.6% |
| 20 | 109.94s / 93.47s / 100.32s | 16/5/8 | 9/15/12 | 75.8% / 76.0% |
| 50 | 230.02s / 219.23s / 228.51s | 16/5/8 | 41/45/42 | 76.7% / 75.8% |
| 100 | 415.57s / 415.08s / 463.65s | 16/5/8 | 91/95/92 | 76.5% / 76.5% |

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

이 문서는 원시 결과에서 자동 생성한 사실표다. 원인과 최종 권고는 [CPU8 MTP·capacity bundle 분석 리포트](../../../reports/results/06_CPU8_MTP_KV_ANALYSIS.md)에 정리한다.
