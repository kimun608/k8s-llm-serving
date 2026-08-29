# CPU vLLM 부하 측정 자동 리포트: mtp-kv-tuned-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`10`, `14.83 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.6~76.7%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 96.5% / 6.34GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.146 | 9.33 | 5.82 / 12.28 | 1.85 / 7.85 | 62.09 / 78.28 | 0 | 12.8% | 7.73 | 6.13GiB |
| 2 | 100.0% | 0.189 | 12.10 | 10.07 / 15.94 | 2.13 / 8.21 | 104.63 / 212.99 | 0 | 24.4% | 7.73 | 6.11GiB |
| 5 | 100.0% | 0.224 | 14.35 | 21.13 / 30.35 | 3.24 / 9.07 | 289.77 / 366.72 | 0 | 60.5% | 7.69 | 6.12GiB |
| 10 | 100.0% | 0.232 | 14.83 | 42.17 / 55.39 | 12.85 / 20.55 | 465.39 / 623.58 | 2 | 96.5% | 7.54 | 6.24GiB |
| 20 | 100.0% | 0.231 | 14.75 | 83.00 / 100.32 | 54.32 / 67.08 | 454.15 / 644.01 | 12 | 96.5% | 7.52 | 6.28GiB |
| 50 | 100.0% | 0.224 | 14.33 | 209.77 / 228.51 | 180.98 / 197.91 | 482.38 / 644.35 | 42 | 96.5% | 7.51 | 6.33GiB |
| 100 | 100.0% | 0.214 | 13.66 | 263.66 / 463.65 | 223.70 / 428.99 | 508.72 / 723.46 | 92 | 96.5% | 7.59 | 6.34GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. baseline과의 before/after 및 개선·악화 원인은 [`reports/results/06_CPU8_MTP_KV_ANALYSIS.md`](../../../reports/results/06_CPU8_MTP_KV_ANALYSIS.md)에서 교차 분석한다.
