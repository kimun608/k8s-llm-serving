# CPU vLLM 부하 측정 자동 리포트: baseline-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `105.33 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 2 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `16 / 90 / 100.0% / 6.27GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.349 | 22.31 | 2.73 / 3.58 | 0.25 / 1.06 | 39.30 / 39.80 | 0 | 7.5% | 7.95 | 5.77GiB |
| 2 | 100.0% | 0.608 | 38.93 | 3.17 / 3.83 | 0.37 / 1.22 | 41.82 / 56.54 | 0 | 13.4% | 7.98 | 5.87GiB |
| 5 | 100.0% | 1.080 | 69.14 | 4.38 / 5.57 | 1.44 / 2.65 | 45.76 / 68.61 | 0 | 32.8% | 7.87 | 6.01GiB |
| 10 | 100.0% | 1.461 | 93.50 | 6.48 / 7.71 | 2.05 / 4.03 | 75.06 / 96.32 | 2 | 64.2% | 7.79 | 6.19GiB |
| 20 | 100.0% | 1.583 | 101.29 | 10.97 / 17.60 | 3.42 / 9.29 | 124.03 / 144.93 | 9 | 100.0% | 7.66 | 6.27GiB |
| 50 | 100.0% | 1.605 | 102.73 | 28.86 / 34.21 | 21.01 / 27.13 | 117.21 / 136.03 | 41 | 100.0% | 7.63 | 6.27GiB |
| 100 | 100.0% | 1.646 | 105.33 | 38.04 / 57.96 | 29.14 / 53.06 | 119.94 / 141.31 | 90 | 100.0% | 7.68 | 6.27GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 비교 설정 측정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../comparison-sequential/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
