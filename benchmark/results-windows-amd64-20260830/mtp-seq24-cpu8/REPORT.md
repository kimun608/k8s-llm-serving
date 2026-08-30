# CPU vLLM 부하 측정 자동 리포트: mtp-seq24-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`10`, `72.82 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.6~76.1%`
- 최대 peak running / waiting / KV / RAM: `5 / 95 / 91.2% / 6.18GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.470 | 30.10 | 1.96 / 2.93 | 0.29 / 1.13 | 26.04 / 34.34 | 0 | 19.3% | 7.92 | 5.98GiB |
| 2 | 100.0% | 0.740 | 47.34 | 2.56 / 3.79 | 0.35 / 1.22 | 33.43 / 51.72 | 0 | 36.8% | 7.96 | 6.08GiB |
| 5 | 100.0% | 1.108 | 70.91 | 4.37 / 5.79 | 0.55 / 1.43 | 59.28 / 78.20 | 0 | 91.2% | 7.95 | 6.16GiB |
| 10 | 100.0% | 1.138 | 72.82 | 8.64 / 10.02 | 4.74 / 5.92 | 60.62 / 79.44 | 5 | 91.2% | 7.95 | 6.18GiB |
| 20 | 100.0% | 1.131 | 72.41 | 17.21 / 19.06 | 13.41 / 14.60 | 60.73 / 80.10 | 15 | 91.2% | 7.95 | 6.18GiB |
| 50 | 100.0% | 1.137 | 72.79 | 41.98 / 44.36 | 38.42 / 40.31 | 61.30 / 79.40 | 45 | 91.2% | 7.96 | 6.18GiB |
| 100 | 100.0% | 1.136 | 72.72 | 45.70 / 84.68 | 41.84 / 80.55 | 58.90 / 81.38 | 95 | 91.2% | 7.95 | 6.18GiB |

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
