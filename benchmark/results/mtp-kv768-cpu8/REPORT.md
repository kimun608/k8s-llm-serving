# CPU vLLM 부하 측정 자동 리포트: mtp-kv768-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `14.85 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.6~76.7%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 96.5% / 6.31GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.127 | 8.13 | 6.67 / 13.21 | 2.11 / 8.64 | 71.39 / 92.20 | 0 | 12.8% | 7.64 | 6.10GiB |
| 2 | 100.0% | 0.166 | 10.63 | 11.21 / 17.22 | 2.44 / 9.45 | 120.27 / 243.50 | 0 | 24.4% | 7.72 | 6.10GiB |
| 5 | 100.0% | 0.194 | 12.39 | 24.81 / 34.85 | 3.25 / 11.63 | 329.74 / 432.54 | 0 | 60.5% | 7.63 | 6.11GiB |
| 10 | 100.0% | 0.202 | 12.95 | 49.62 / 60.17 | 14.84 / 22.14 | 538.48 / 740.37 | 2 | 96.5% | 7.54 | 6.25GiB |
| 20 | 100.0% | 0.205 | 13.10 | 95.63 / 114.02 | 62.67 / 73.09 | 514.80 / 745.59 | 12 | 96.5% | 7.46 | 6.27GiB |
| 50 | 100.0% | 0.224 | 14.35 | 207.00 / 234.23 | 180.51 / 198.74 | 479.62 / 643.28 | 42 | 96.5% | 7.59 | 6.27GiB |
| 100 | 100.0% | 0.232 | 14.85 | 246.01 / 425.92 | 211.72 / 386.55 | 448.67 / 691.76 | 92 | 96.5% | 7.56 | 6.31GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. baseline과의 before/after 및 개선·악화 원인은 [`reports/results/07_FINAL_COMPREHENSIVE_ANALYSIS.md`](../../../reports/results/07_FINAL_COMPREHENSIVE_ANALYSIS.md)에서 교차 분석한다.
