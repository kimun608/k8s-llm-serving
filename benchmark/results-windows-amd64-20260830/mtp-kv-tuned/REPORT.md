# CPU vLLM 부하 측정 자동 리포트: mtp-kv-tuned

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`20`, `62.34 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.7~76.0%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 97.7% / 6.58GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.356 | 22.79 | 2.59 / 3.78 | 0.35 / 1.38 | 35.19 / 46.20 | 0 | 12.8% | 6.00 | 6.20GiB |
| 2 | 100.0% | 0.553 | 35.42 | 3.48 / 4.96 | 0.46 / 1.54 | 45.01 / 66.54 | 0 | 24.4% | 6.00 | 6.32GiB |
| 5 | 100.0% | 0.852 | 54.51 | 5.67 / 7.56 | 0.66 / 1.68 | 78.83 / 101.78 | 0 | 60.5% | 6.00 | 6.39GiB |
| 10 | 100.0% | 0.971 | 62.13 | 10.14 / 13.06 | 2.70 / 4.62 | 113.98 / 149.65 | 2 | 96.5% | 6.00 | 6.58GiB |
| 20 | 100.0% | 0.974 | 62.34 | 19.59 / 22.74 | 12.69 / 14.38 | 113.56 / 150.37 | 12 | 96.5% | 5.99 | 6.57GiB |
| 50 | 100.0% | 0.974 | 62.32 | 48.56 / 53.08 | 42.50 / 45.13 | 116.43 / 147.01 | 42 | 95.3% | 5.99 | 6.57GiB |
| 100 | 100.0% | 0.973 | 62.27 | 55.77 / 99.14 | 48.48 / 92.83 | 111.38 / 153.30 | 92 | 97.7% | 5.99 | 6.58GiB |

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
