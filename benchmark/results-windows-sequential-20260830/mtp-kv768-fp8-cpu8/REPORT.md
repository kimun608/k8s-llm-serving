# CPU vLLM 부하 측정 자동 리포트: mtp-kv768-fp8-cpu8

## 검증 요약

- 완료 요청: `700/700`
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`100`, `84.39 token/s`
- 최초 scheduler waiting: C=`10`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `74.3~92.7%`
- 최대 peak running / waiting / KV / RAM: `9 / 91 / 93.8% / 6.66GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.528 | 33.79 | 1.79 / 2.56 | 0.29 / 1.17 | 22.00 / 29.05 | 0 | 10.4% | 7.92 | 6.21GiB |
| 2 | 100.0% | 0.749 | 47.95 | 2.62 / 3.52 | 0.35 / 1.21 | 32.25 / 49.17 | 0 | 20.8% | 7.97 | 6.32GiB |
| 5 | 100.0% | 1.115 | 71.35 | 4.32 / 5.59 | 0.47 / 1.34 | 60.15 / 75.37 | 0 | 52.1% | 7.95 | 6.39GiB |
| 10 | 100.0% | 1.310 | 83.82 | 7.44 / 9.69 | 1.37 / 2.59 | 95.85 / 124.46 | 1 | 93.8% | 7.92 | 6.57GiB |
| 20 | 100.0% | 1.302 | 83.35 | 14.70 / 16.73 | 8.77 / 10.35 | 95.53 / 122.78 | 11 | 93.8% | 7.92 | 6.57GiB |
| 50 | 100.0% | 1.308 | 83.72 | 35.84 / 39.50 | 30.49 / 33.42 | 95.05 / 133.26 | 41 | 93.8% | 7.91 | 6.60GiB |
| 100 | 100.0% | 1.319 | 84.39 | 42.04 / 75.25 | 36.28 / 70.48 | 92.86 / 127.45 | 91 | 93.8% | 7.92 | 6.66GiB |

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
