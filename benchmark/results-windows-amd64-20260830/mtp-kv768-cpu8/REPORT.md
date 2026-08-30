# CPU vLLM 부하 측정 자동 리포트: mtp-kv768-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `81.94 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.7~76.3%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 96.5% / 6.60GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.473 | 30.27 | 1.95 / 2.88 | 0.27 / 1.09 | 26.06 / 34.50 | 0 | 12.8% | 7.93 | 6.23GiB |
| 2 | 100.0% | 0.733 | 46.88 | 2.61 / 3.81 | 0.36 / 1.24 | 33.72 / 51.70 | 0 | 24.4% | 7.96 | 6.33GiB |
| 5 | 100.0% | 1.118 | 71.58 | 4.28 / 5.82 | 0.53 / 1.37 | 59.56 / 77.46 | 0 | 60.5% | 7.96 | 6.40GiB |
| 10 | 100.0% | 1.251 | 80.04 | 7.84 / 9.67 | 2.08 / 3.24 | 90.32 / 117.86 | 2 | 95.3% | 7.93 | 6.55GiB |
| 20 | 100.0% | 1.258 | 80.52 | 15.14 / 18.20 | 9.84 / 11.40 | 87.33 / 119.06 | 12 | 96.5% | 7.92 | 6.56GiB |
| 50 | 100.0% | 1.271 | 81.36 | 36.95 / 40.61 | 32.01 / 34.47 | 86.67 / 116.14 | 42 | 96.5% | 7.92 | 6.58GiB |
| 100 | 100.0% | 1.280 | 81.94 | 42.33 / 76.44 | 36.70 / 70.35 | 88.12 / 114.99 | 92 | 96.5% | 7.93 | 6.60GiB |

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
