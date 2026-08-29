# CPU vLLM 부하 측정 자동 리포트: baseline-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`20`, `16.22 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 2 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `16 / 91 / 100.0% / 6.15GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.101 | 6.44 | 9.14 / 15.61 | 1.93 / 8.16 | 114.11 / 121.04 | 0 | 7.5% | 7.78 | 6.15GiB |
| 2 | 100.0% | 0.145 | 9.28 | 13.03 / 18.54 | 3.07 / 9.61 | 134.94 / 247.66 | 0 | 13.4% | 7.78 | 5.93GiB |
| 5 | 100.0% | 0.206 | 13.16 | 23.05 / 34.32 | 12.91 / 25.66 | 137.46 / 355.07 | 0 | 32.8% | 6.90 | 6.08GiB |
| 10 | 100.0% | 0.233 | 14.94 | 42.80 / 53.92 | 18.80 / 34.09 | 383.11 / 607.88 | 1 | 64.2% | 6.89 | 5.88GiB |
| 20 | 100.0% | 0.253 | 16.22 | 72.59 / 109.94 | 29.04 / 54.48 | 692.92 / 1030.33 | 9 | 100.0% | 6.76 | 5.92GiB |
| 50 | 100.0% | 0.235 | 15.03 | 205.54 / 230.02 | 157.39 / 180.73 | 718.71 / 1004.65 | 41 | 100.0% | 6.89 | 5.88GiB |
| 100 | 100.0% | 0.237 | 15.15 | 279.11 / 415.57 | 219.64 / 387.86 | 690.07 / 1001.24 | 91 | 100.0% | 6.81 | 5.89GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. baseline과의 before/after 및 개선·악화 원인은 [`reports/results/05_BASELINE_CPU8_ANALYSIS.md`](../../../reports/results/05_BASELINE_CPU8_ANALYSIS.md)에서 교차 분석한다.
