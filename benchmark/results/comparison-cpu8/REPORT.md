# Baseline CPU limit 6 vs 8 자동 비교

## 검증

- 비교 요청: `1400`건, 실패 `0`건
- prompt SHA-256, 모델, image args, memory, CPU request, KV, scheduler, sampling과 workload가 동일함
- 유일한 serving 변경은 container CPU limit `6 → 8`
- client/server prompt와 generation token counter가 모든 단계에서 일치함
- 정식 phase의 UTC wall clock과 monotonic timer 오차가 1%/5초 이내이며 metric scrape error가 없음
- 교체 전 표본과 사유는 원본 보존함: `baseline C=2, baseline-cpu8 C=10, baseline-cpu8 C=5`
- 전체 OOM kill 증가량: `0`

## 결과

| C | Output tok/s 6 → 8 | 변화 | E2E p95 6 → 8 | 변화 | TPOT p95 6 → 8 | 변화 | Avg CPU 6 → 8 | Peak run/wait 6 → 8 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5.16 → 6.44 | +24.8% | 19.00s → 15.61s | -17.8% | 152.37ms → 121.04ms | -20.6% | 5.99 → 7.78 | 1/0 → 1/0 |
| 2 | 7.64 → 9.28 | +21.4% | 22.32s → 18.54s | -16.9% | 319.15ms → 247.66ms | -22.4% | 5.99 → 7.78 | 2/0 → 2/0 |
| 5 | 11.28 → 13.16 | +16.7% | 38.92s → 34.32s | -11.8% | 422.60ms → 355.07ms | -16.0% | 5.55 → 6.90 | 5/0 → 5/0 |
| 10 | 12.06 → 14.94 | +23.9% | 66.80s → 53.92s | -19.3% | 753.07ms → 607.88ms | -19.3% | 5.52 → 6.89 | 10/1 → 10/1 |
| 20 | 13.50 → 16.22 | +20.2% | 131.17s → 109.94s | -16.2% | 1040.10ms → 1030.33ms | -0.9% | 5.46 → 6.76 | 16/11 → 16/9 |
| 50 | 13.46 → 15.03 | +11.7% | 254.46s → 230.02s | -9.6% | 1038.46ms → 1004.65ms | -3.3% | 5.50 → 6.89 | 16/40 → 16/41 |
| 100 | 13.54 → 15.15 | +11.8% | 464.06s → 415.57s | -10.4% | 1214.28ms → 1001.24ms | -17.5% | 5.54 → 6.81 | 16/91 → 16/91 |

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
