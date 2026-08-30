# CPU vLLM 부하 측정 자동 리포트: mtp-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`20`, `72.99 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.7~76.0%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 6.21GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.476 | 30.48 | 1.94 / 2.92 | 0.28 / 1.09 | 25.88 / 33.83 | 0 | 19.3% | 7.94 | 5.98GiB |
| 2 | 100.0% | 0.741 | 47.45 | 2.60 / 3.80 | 0.35 / 1.22 | 32.96 / 50.35 | 0 | 36.8% | 7.97 | 6.08GiB |
| 5 | 100.0% | 1.116 | 71.41 | 4.28 / 5.85 | 0.52 / 1.42 | 59.67 / 77.17 | 0 | 91.2% | 7.95 | 6.16GiB |
| 10 | 100.0% | 1.138 | 72.85 | 8.59 / 9.89 | 4.80 / 5.85 | 60.49 / 79.98 | 5 | 91.2% | 7.96 | 6.16GiB |
| 20 | 100.0% | 1.141 | 72.99 | 17.12 / 18.84 | 13.31 / 14.30 | 60.30 / 80.76 | 15 | 91.2% | 7.96 | 6.16GiB |
| 50 | 100.0% | 1.139 | 72.89 | 41.89 / 44.38 | 38.33 / 40.45 | 59.94 / 77.72 | 45 | 91.2% | 7.96 | 6.18GiB |
| 100 | 100.0% | 1.135 | 72.66 | 45.92 / 84.75 | 42.28 / 80.30 | 58.91 / 83.75 | 95 | 91.2% | 7.95 | 6.21GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 비교 설정 측정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../comparison-sequential/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
