# CPU vLLM 부하 측정 자동 리포트: mtp-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`20`, `72.13 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.7~76.0%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 6.17GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.472 | 30.22 | 1.94 / 2.94 | 0.29 / 1.13 | 25.90 / 34.45 | 0 | 19.3% | 7.89 | 5.98GiB |
| 2 | 100.0% | 0.742 | 47.46 | 2.62 / 3.75 | 0.35 / 1.24 | 33.05 / 50.86 | 0 | 36.8% | 7.96 | 6.09GiB |
| 5 | 100.0% | 1.107 | 70.83 | 4.31 / 5.87 | 0.53 / 1.42 | 60.76 / 77.56 | 0 | 91.2% | 7.95 | 6.15GiB |
| 10 | 100.0% | 1.116 | 71.41 | 8.80 / 10.19 | 4.90 / 5.89 | 61.56 / 80.64 | 5 | 91.2% | 7.95 | 6.17GiB |
| 20 | 100.0% | 1.127 | 72.13 | 17.23 / 18.99 | 13.52 / 14.75 | 61.00 / 78.23 | 15 | 91.2% | 7.96 | 6.16GiB |
| 50 | 100.0% | 1.121 | 71.75 | 42.49 / 45.32 | 39.13 / 41.21 | 60.97 / 83.51 | 45 | 91.2% | 7.95 | 6.16GiB |
| 100 | 100.0% | 1.113 | 71.22 | 46.96 / 87.42 | 44.03 / 84.54 | 60.15 / 85.83 | 95 | 91.2% | 7.94 | 6.17GiB |

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
