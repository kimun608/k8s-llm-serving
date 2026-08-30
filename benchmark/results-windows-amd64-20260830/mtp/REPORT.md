# CPU vLLM 부하 측정 자동 리포트: mtp

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `55.06 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.6~76.1%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 7.63GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.350 | 22.42 | 2.64 / 3.84 | 0.37 / 1.39 | 35.77 / 46.77 | 0 | 19.3% | 5.98 | 7.26GiB |
| 2 | 100.0% | 0.551 | 35.25 | 3.49 / 4.94 | 0.45 / 1.53 | 45.86 / 69.16 | 0 | 36.8% | 6.00 | 7.36GiB |
| 5 | 100.0% | 0.841 | 53.85 | 5.73 / 7.55 | 0.69 / 1.75 | 78.42 / 102.94 | 0 | 91.2% | 6.00 | 7.45GiB |
| 10 | 100.0% | 0.852 | 54.55 | 11.50 / 13.26 | 6.44 / 7.67 | 80.23 / 106.83 | 5 | 91.2% | 6.00 | 7.45GiB |
| 20 | 100.0% | 0.839 | 53.71 | 23.25 / 25.42 | 18.08 / 19.76 | 82.14 / 107.75 | 15 | 91.2% | 5.99 | 7.50GiB |
| 50 | 100.0% | 0.856 | 54.81 | 56.52 / 59.29 | 51.67 / 53.98 | 79.20 / 106.93 | 45 | 91.2% | 5.99 | 7.50GiB |
| 100 | 100.0% | 0.860 | 55.06 | 59.81 / 111.75 | 55.54 / 107.33 | 77.33 / 107.84 | 95 | 91.2% | 5.99 | 7.63GiB |

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
