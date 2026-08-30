# CPU vLLM 부하 측정 자동 리포트: baseline-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `105.19 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 3 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `16 / 90 / 100.0% / 6.02GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.348 | 22.29 | 2.73 / 3.57 | 0.24 / 1.04 | 39.45 / 39.93 | 0 | 7.5% | 7.96 | 5.53GiB |
| 2 | 100.0% | 0.610 | 39.04 | 3.16 / 3.84 | 0.36 / 1.19 | 41.54 / 55.82 | 0 | 13.4% | 7.97 | 5.62GiB |
| 5 | 100.0% | 1.075 | 68.82 | 4.43 / 5.56 | 1.43 / 2.63 | 46.32 / 69.44 | 0 | 32.8% | 7.88 | 5.78GiB |
| 10 | 100.0% | 1.475 | 94.39 | 6.45 / 7.77 | 2.34 / 4.05 | 73.01 / 95.90 | 1 | 64.2% | 7.77 | 5.95GiB |
| 20 | 100.0% | 1.603 | 102.59 | 10.95 / 17.43 | 3.21 / 9.28 | 119.71 / 138.46 | 11 | 100.0% | 7.68 | 5.98GiB |
| 50 | 100.0% | 1.590 | 101.74 | 28.96 / 34.51 | 20.94 / 27.32 | 117.83 / 144.00 | 41 | 100.0% | 7.63 | 6.00GiB |
| 100 | 100.0% | 1.644 | 105.19 | 37.19 / 58.06 | 29.27 / 52.00 | 118.00 / 140.94 | 90 | 100.0% | 7.70 | 6.02GiB |

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
