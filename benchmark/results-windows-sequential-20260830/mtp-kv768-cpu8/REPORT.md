# CPU vLLM 부하 측정 자동 리포트: mtp-kv768-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `82.67 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.7~76.4%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 96.5% / 6.62GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.476 | 30.45 | 1.94 / 2.88 | 0.28 / 1.12 | 26.03 / 34.33 | 0 | 12.8% | 7.93 | 6.22GiB |
| 2 | 100.0% | 0.745 | 47.69 | 2.56 / 3.70 | 0.34 / 1.20 | 33.23 / 50.86 | 0 | 24.4% | 7.97 | 6.32GiB |
| 5 | 100.0% | 1.124 | 71.95 | 4.31 / 5.78 | 0.50 / 1.31 | 59.98 / 78.49 | 0 | 60.5% | 7.95 | 6.40GiB |
| 10 | 100.0% | 1.253 | 80.16 | 7.83 / 9.74 | 2.12 / 3.34 | 86.98 / 117.81 | 2 | 96.5% | 7.92 | 6.48GiB |
| 20 | 100.0% | 1.268 | 81.16 | 15.25 / 18.18 | 9.86 / 11.62 | 85.83 / 113.68 | 12 | 96.5% | 7.92 | 6.55GiB |
| 50 | 100.0% | 1.269 | 81.19 | 36.68 / 40.39 | 32.08 / 34.26 | 86.14 / 116.84 | 42 | 96.5% | 7.93 | 6.62GiB |
| 100 | 100.0% | 1.292 | 82.67 | 42.05 / 76.08 | 36.35 / 70.84 | 87.28 / 112.82 | 92 | 96.5% | 7.93 | 6.62GiB |

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
