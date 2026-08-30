# CPU vLLM 부하 측정 자동 리포트: mtp-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`50`, `72.78 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.7~76.0%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 8.00GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.475 | 30.43 | 1.93 / 2.91 | 0.28 / 1.13 | 25.91 / 34.02 | 0 | 19.3% | 7.94 | 7.95GiB |
| 2 | 100.0% | 0.746 | 47.74 | 2.56 / 3.70 | 0.35 / 1.18 | 33.16 / 48.91 | 0 | 36.8% | 7.97 | 8.00GiB |
| 5 | 100.0% | 1.110 | 71.03 | 4.34 / 5.85 | 0.54 / 1.47 | 60.40 / 77.13 | 0 | 91.2% | 7.96 | 8.00GiB |
| 10 | 100.0% | 1.114 | 71.32 | 8.94 / 10.25 | 4.89 / 5.94 | 62.13 / 81.35 | 5 | 91.2% | 7.95 | 8.00GiB |
| 20 | 100.0% | 1.115 | 71.36 | 17.48 / 19.22 | 13.62 / 14.56 | 61.22 / 84.33 | 15 | 91.2% | 7.94 | 8.00GiB |
| 50 | 100.0% | 1.137 | 72.78 | 41.66 / 44.50 | 38.07 / 40.34 | 60.26 / 78.50 | 45 | 91.2% | 7.96 | 8.00GiB |
| 100 | 100.0% | 1.130 | 72.34 | 45.37 / 85.43 | 42.33 / 80.97 | 60.11 / 82.09 | 95 | 91.2% | 7.95 | 8.00GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 비교 설정 측정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../comparison-cpu8-factors/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
