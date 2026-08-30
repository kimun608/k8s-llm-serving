# CPU vLLM 부하 측정 자동 리포트: baseline-kv768-fp8-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`50`, `113.23 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `20 / 91 / 71.4% / 6.51GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.350 | 22.42 | 2.72 / 3.51 | 0.24 / 1.04 | 39.21 / 39.66 | 0 | 3.6% | 7.96 | 6.15GiB |
| 2 | 100.0% | 0.607 | 38.83 | 3.18 / 3.84 | 0.38 / 1.23 | 42.05 / 56.76 | 0 | 7.1% | 7.98 | 6.19GiB |
| 5 | 100.0% | 1.084 | 69.37 | 4.36 / 5.61 | 1.43 / 2.70 | 45.72 / 68.62 | 0 | 17.9% | 7.87 | 6.26GiB |
| 10 | 100.0% | 1.464 | 93.70 | 6.53 / 7.89 | 2.36 / 4.12 | 72.89 / 95.64 | 2 | 35.7% | 7.75 | 6.47GiB |
| 20 | 100.0% | 1.763 | 112.86 | 11.25 / 13.42 | 3.24 / 6.70 | 126.63 / 147.36 | 11 | 71.4% | 7.63 | 6.47GiB |
| 50 | 100.0% | 1.769 | 113.23 | 24.77 / 33.26 | 15.72 / 25.24 | 146.91 / 170.60 | 40 | 71.4% | 7.63 | 6.51GiB |
| 100 | 100.0% | 1.763 | 112.86 | 34.99 / 56.47 | 25.99 / 49.68 | 139.82 / 165.64 | 91 | 71.4% | 7.62 | 6.51GiB |

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
