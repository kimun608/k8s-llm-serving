# CPU vLLM 부하 측정 자동 리포트: baseline-cpu8-fp8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `109.44 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `18 / 91 / 97.3% / 6.27GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.351 | 22.45 | 2.72 / 3.53 | 0.25 / 1.07 | 39.03 / 39.57 | 0 | 5.4% | 7.96 | 5.97GiB |
| 2 | 100.0% | 0.611 | 39.10 | 3.18 / 3.75 | 0.36 / 1.19 | 41.82 / 56.14 | 0 | 10.8% | 7.99 | 5.97GiB |
| 5 | 100.0% | 1.085 | 69.42 | 4.42 / 5.53 | 1.44 / 2.62 | 45.64 / 68.79 | 0 | 27.0% | 7.88 | 6.03GiB |
| 10 | 100.0% | 1.431 | 91.58 | 6.72 / 7.86 | 2.11 / 4.03 | 76.46 / 100.19 | 2 | 54.1% | 7.76 | 6.19GiB |
| 20 | 100.0% | 1.706 | 109.18 | 10.97 / 17.05 | 3.21 / 7.49 | 121.06 / 152.39 | 11 | 97.3% | 7.74 | 6.25GiB |
| 50 | 100.0% | 1.681 | 107.56 | 26.18 / 32.57 | 20.12 / 24.56 | 128.35 / 142.56 | 41 | 97.3% | 7.57 | 6.27GiB |
| 100 | 100.0% | 1.710 | 109.44 | 33.98 / 58.26 | 25.71 / 53.44 | 129.74 / 153.01 | 91 | 97.3% | 7.66 | 6.27GiB |

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
