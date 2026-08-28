# CPU vLLM 부하 측정 자동 리포트: mtp-seq24-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`50`, `14.46 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.4~76.7%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 93.0% / 6.12GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.140 | 8.97 | 6.06 / 12.39 | 2.00 / 8.30 | 63.54 / 79.28 | 0 | 19.3% | 7.75 | 6.12GiB |
| 2 | 100.0% | 0.188 | 12.04 | 10.33 / 15.91 | 2.15 / 8.55 | 103.68 / 221.27 | 0 | 36.8% | 7.76 | 6.04GiB |
| 5 | 100.0% | 0.223 | 14.30 | 21.38 / 30.81 | 2.93 / 9.73 | 285.98 / 371.52 | 0 | 91.2% | 7.72 | 6.04GiB |
| 10 | 100.0% | 0.224 | 14.36 | 43.70 / 53.27 | 24.83 / 32.49 | 280.82 / 398.38 | 5 | 91.2% | 7.64 | 6.05GiB |
| 20 | 100.0% | 0.225 | 14.40 | 86.97 / 96.26 | 68.36 / 76.40 | 287.84 / 409.26 | 15 | 91.2% | 7.64 | 6.06GiB |
| 50 | 100.0% | 0.226 | 14.46 | 211.02 / 226.52 | 195.41 / 208.17 | 283.80 / 428.62 | 45 | 93.0% | 7.65 | 6.06GiB |
| 100 | 100.0% | 0.224 | 14.35 | 238.83 / 437.33 | 215.31 / 412.27 | 285.40 / 427.51 | 95 | 91.2% | 7.62 | 6.07GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. baseline과의 before/after 및 개선·악화 원인은 [`reports/07_FINAL_COMPREHENSIVE_ANALYSIS.md`](../../../reports/07_FINAL_COMPREHENSIVE_ANALYSIS.md)에서 교차 분석한다.
