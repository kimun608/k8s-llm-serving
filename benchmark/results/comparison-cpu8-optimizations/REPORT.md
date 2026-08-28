# CPU limit 8: Baseline vs MTP vs MTP+KV 자동 비교

## 검증

- 비교 요청: `2100`건, 실패 `0`건
- 세 설정 모두 CPU request/limit `4/8`, 동일 image/model/memory/workload를 사용함
- 유일한 단계 변경은 MTP 추가, 이어서 KV `512→768MiB`와 max sequences `20→24` 추가임
- client/server token counter, wall/monotonic timer, metric scrape를 모든 phase에서 검증함
- 전체 OOM kill 증가량: `0`

## 결과

| C | Output tok/s base / MTP / MTP+KV | MTP vs base | Combined vs base | E2E p95 base → combined | Peak run/wait base / MTP / combined | Acceptance MTP / combined |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.44 / 8.24 / 9.33 | +27.8% | +44.8% | 15.61s → 12.28s | 1/0 / 1/0 / 1/0 | 76.7% / 76.7% |
| 2 | 9.28 / 10.30 / 12.10 | +11.0% | +30.4% | 18.54s → 15.94s | 2/0 / 2/0 / 2/0 | 76.2% / 76.3% |
| 5 | 13.16 / 14.38 / 14.35 | +9.3% | +9.0% | 34.32s → 30.35s | 5/0 / 5/0 / 5/0 | 75.2% / 76.1% |
| 10 | 14.94 / 14.41 / 14.83 | -3.5% | -0.8% | 53.92s → 55.39s | 10/1 / 5/5 / 8/2 | 75.6% / 75.6% |
| 20 | 16.22 / 14.62 / 14.75 | -9.9% | -9.0% | 109.94s → 100.32s | 16/9 / 5/15 / 8/12 | 75.8% / 76.0% |
| 50 | 15.03 / 14.89 / 14.33 | -0.9% | -4.6% | 230.02s → 228.51s | 16/41 / 5/45 / 8/42 | 76.7% / 75.8% |
| 100 | 15.15 / 15.18 / 13.66 | +0.2% | -9.8% | 415.57s → 463.65s | 16/91 / 5/95 / 8/92 | 76.5% / 76.5% |

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

이 문서는 원시 결과에서 자동 생성한 사실표다. 원인과 최종 권고는 [CPU8 MTP·KV 분석 리포트](../../../reports/06_CPU8_MTP_KV_ANALYSIS.md)에 정리한다.
