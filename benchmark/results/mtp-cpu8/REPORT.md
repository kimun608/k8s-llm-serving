# CPU vLLM 부하 측정 자동 리포트: mtp-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `15.18 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.2~76.7%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 6.10GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.129 | 8.24 | 6.62 / 13.35 | 2.18 / 8.90 | 68.33 / 91.47 | 0 | 19.3% | 7.71 | 6.10GiB |
| 2 | 100.0% | 0.161 | 10.30 | 11.82 / 18.42 | 2.59 / 9.86 | 120.34 / 257.10 | 0 | 36.8% | 7.75 | 6.04GiB |
| 5 | 100.0% | 0.225 | 14.38 | 21.53 / 30.22 | 3.36 / 9.33 | 285.03 / 353.43 | 0 | 91.2% | 7.73 | 6.02GiB |
| 10 | 100.0% | 0.225 | 14.41 | 43.79 / 52.75 | 25.34 / 31.30 | 291.25 / 414.52 | 5 | 91.2% | 7.69 | 6.01GiB |
| 20 | 100.0% | 0.228 | 14.62 | 85.95 / 93.47 | 67.74 / 77.13 | 286.75 / 386.05 | 15 | 91.2% | 7.65 | 6.01GiB |
| 50 | 100.0% | 0.233 | 14.89 | 203.60 / 219.23 | 186.25 / 201.18 | 278.47 / 374.28 | 45 | 91.2% | 7.70 | 6.01GiB |
| 100 | 100.0% | 0.237 | 15.18 | 227.13 / 415.08 | 207.39 / 391.28 | 268.57 / 405.88 | 95 | 91.2% | 7.74 | 6.01GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. baseline과의 before/after 및 개선·악화 원인은 [`reports/06_CPU8_MTP_KV_ANALYSIS.md`](../../../reports/06_CPU8_MTP_KV_ANALYSIS.md)에서 교차 분석한다.
