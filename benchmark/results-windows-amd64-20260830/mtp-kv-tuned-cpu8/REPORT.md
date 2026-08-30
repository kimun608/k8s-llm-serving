# CPU vLLM 부하 측정 자동 리포트: mtp-kv-tuned-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`50`, `82.04 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `75.8~76.2%`
- 최대 peak running / waiting / KV / RAM: `8 / 92 / 96.5% / 6.70GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.476 | 30.49 | 1.94 / 2.89 | 0.28 / 1.13 | 25.96 / 34.37 | 0 | 12.8% | 7.94 | 6.21GiB |
| 2 | 100.0% | 0.744 | 47.61 | 2.56 / 3.69 | 0.35 / 1.19 | 33.64 / 50.04 | 0 | 24.4% | 7.98 | 6.32GiB |
| 5 | 100.0% | 1.121 | 71.73 | 4.27 / 5.88 | 0.51 / 1.38 | 59.17 / 76.91 | 0 | 60.5% | 7.96 | 6.39GiB |
| 10 | 100.0% | 1.252 | 80.10 | 7.78 / 9.90 | 2.03 / 3.35 | 87.04 / 119.08 | 2 | 96.5% | 7.92 | 6.54GiB |
| 20 | 100.0% | 1.278 | 81.81 | 15.06 / 17.53 | 9.74 / 11.30 | 85.26 / 118.59 | 12 | 96.5% | 7.92 | 6.69GiB |
| 50 | 100.0% | 1.282 | 82.04 | 36.74 / 40.08 | 31.84 / 34.04 | 86.24 / 116.13 | 42 | 95.3% | 7.94 | 6.70GiB |
| 100 | 100.0% | 1.274 | 81.51 | 43.25 / 76.61 | 38.20 / 71.98 | 85.64 / 113.27 | 92 | 95.3% | 7.92 | 6.70GiB |

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
