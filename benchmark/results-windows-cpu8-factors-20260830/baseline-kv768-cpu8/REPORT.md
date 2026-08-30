# CPU vLLM 부하 측정 자동 리포트: baseline-kv768-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `113.14 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `20 / 90 / 84.2% / 7.50GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.349 | 22.35 | 2.72 / 3.56 | 0.26 / 1.10 | 39.10 / 39.76 | 0 | 5.0% | 7.96 | 6.99GiB |
| 2 | 100.0% | 0.609 | 39.00 | 3.16 / 3.79 | 0.37 / 1.22 | 41.85 / 56.20 | 0 | 8.9% | 7.98 | 7.07GiB |
| 5 | 100.0% | 1.074 | 68.75 | 4.40 / 5.59 | 1.46 / 2.65 | 46.11 / 69.75 | 0 | 21.8% | 7.87 | 7.22GiB |
| 10 | 100.0% | 1.457 | 93.25 | 6.54 / 7.77 | 2.04 / 3.90 | 75.61 / 96.94 | 2 | 42.6% | 7.80 | 7.40GiB |
| 20 | 100.0% | 1.767 | 113.06 | 11.29 / 13.50 | 3.30 / 6.74 | 125.33 / 147.11 | 11 | 83.2% | 7.63 | 7.44GiB |
| 50 | 100.0% | 1.759 | 112.57 | 25.84 / 34.18 | 16.64 / 23.82 | 142.24 / 167.17 | 41 | 84.2% | 7.60 | 7.47GiB |
| 100 | 100.0% | 1.768 | 113.14 | 35.23 / 56.33 | 25.73 / 50.60 | 141.48 / 156.28 | 90 | 83.2% | 7.60 | 7.50GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 비교 설정 측정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../comparison-cpu8-factors/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
