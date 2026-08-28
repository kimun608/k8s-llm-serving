# CPU vLLM 부하 측정 자동 리포트: mtp

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`50`, `12.31 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.1~76.7%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 6.14GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.122 | 7.80 | 6.93 / 14.46 | 2.26 / 9.61 | 72.88 / 91.02 | 0 | 19.3% | 5.99 | 6.14GiB |
| 2 | 100.0% | 0.156 | 9.99 | 12.11 / 19.50 | 2.51 / 10.39 | 122.69 / 275.01 | 0 | 36.8% | 5.99 | 5.99GiB |
| 5 | 100.0% | 0.185 | 11.87 | 25.92 / 37.32 | 4.04 / 12.34 | 345.65 / 450.97 | 0 | 91.2% | 5.98 | 5.99GiB |
| 10 | 100.0% | 0.185 | 11.81 | 53.02 / 63.28 | 30.57 / 39.10 | 357.24 / 457.64 | 5 | 91.2% | 5.98 | 5.99GiB |
| 20 | 100.0% | 0.184 | 11.78 | 105.70 / 114.00 | 84.37 / 92.11 | 344.99 / 469.90 | 15 | 91.2% | 5.96 | 5.99GiB |
| 50 | 100.0% | 0.192 | 12.31 | 251.77 / 276.43 | 231.98 / 252.10 | 341.56 / 468.58 | 45 | 91.2% | 5.97 | 6.00GiB |
| 100 | 100.0% | 0.188 | 12.05 | 283.83 / 522.12 | 258.71 / 506.12 | 332.71 / 523.22 | 95 | 91.2% | 5.97 | 5.99GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. baseline과의 before/after 및 개선·악화 원인은 [`reports/04_OPTIMIZATION_FINAL_ANALYSIS.md`](../../../reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)에서 교차 분석한다.
