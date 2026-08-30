# CPU vLLM 부하 측정 자동 리포트: baseline-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `104.06 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 2 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `16 / 90 / 100.0% / 8.00GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.344 | 22.02 | 2.76 / 3.60 | 0.25 / 1.07 | 39.64 / 41.31 | 0 | 7.5% | 7.94 | 8.00GiB |
| 2 | 100.0% | 0.605 | 38.73 | 3.20 / 3.84 | 0.36 / 1.24 | 42.19 / 56.58 | 0 | 13.4% | 7.97 | 8.00GiB |
| 5 | 100.0% | 1.071 | 68.56 | 4.43 / 5.58 | 1.50 / 2.69 | 45.80 / 69.67 | 0 | 32.8% | 7.86 | 8.00GiB |
| 10 | 100.0% | 1.466 | 93.79 | 6.93 / 7.68 | 2.44 / 4.14 | 71.70 / 94.33 | 1 | 64.2% | 7.69 | 8.00GiB |
| 20 | 100.0% | 1.624 | 103.93 | 10.85 / 17.31 | 3.46 / 9.18 | 118.88 / 141.15 | 11 | 100.0% | 7.67 | 8.00GiB |
| 50 | 100.0% | 1.600 | 102.40 | 29.39 / 35.18 | 21.43 / 27.06 | 111.50 / 145.58 | 39 | 100.0% | 7.65 | 8.00GiB |
| 100 | 100.0% | 1.626 | 104.06 | 37.23 / 58.52 | 29.01 / 52.46 | 116.88 / 140.32 | 90 | 100.0% | 7.65 | 8.00GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 8개 설정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../comparison-all/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
