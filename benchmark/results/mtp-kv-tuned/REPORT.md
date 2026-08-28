# CPU vLLM 부하 측정 자동 리포트: mtp-kv-tuned

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`50`, `12.52 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `74.8~76.7%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 96.5% / 6.29GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.116 | 7.43 | 7.23 / 15.36 | 2.30 / 9.93 | 77.48 / 97.08 | 0 | 12.8% | 5.99 | 6.13GiB |
| 2 | 100.0% | 0.156 | 10.01 | 11.83 / 19.25 | 2.64 / 10.39 | 121.74 / 273.35 | 0 | 24.4% | 5.99 | 6.13GiB |
| 5 | 100.0% | 0.178 | 11.40 | 26.55 / 37.73 | 4.05 / 11.69 | 364.90 / 469.08 | 0 | 60.5% | 5.98 | 6.15GiB |
| 10 | 100.0% | 0.180 | 11.51 | 53.53 / 71.46 | 17.49 / 26.17 | 594.22 / 808.84 | 2 | 96.5% | 5.87 | 6.26GiB |
| 20 | 100.0% | 0.185 | 11.84 | 105.30 / 127.53 | 69.30 / 80.55 | 583.22 / 817.05 | 12 | 96.5% | 5.93 | 6.26GiB |
| 50 | 100.0% | 0.196 | 12.52 | 240.60 / 261.42 | 209.49 / 222.69 | 539.77 / 730.22 | 42 | 95.3% | 5.94 | 6.27GiB |
| 100 | 100.0% | 0.192 | 12.29 | 287.71 / 510.03 | 246.04 / 479.05 | 550.89 / 767.99 | 92 | 96.5% | 5.93 | 6.29GiB |

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
