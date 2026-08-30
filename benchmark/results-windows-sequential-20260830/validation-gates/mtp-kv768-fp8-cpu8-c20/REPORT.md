# CPU vLLM 부하 측정 자동 리포트: mtp-kv768-fp8-cpu8

## 검증 요약

- 완료 요청: `20/20`
- 동시성: `20`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`20`, `76.97 token/s`
- 최초 scheduler waiting: C=`20`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `66.8~66.8%`
- 최대 peak running / waiting / KV / RAM: `9 / 11 / 93.8% / 7.57GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 100.0% | 1.203 | 76.97 | 12.18 / 16.25 | 6.39 / 12.78 | 87.79 / 114.37 | 11 | 93.8% | 7.74 | 7.57GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 비교 설정 측정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../../comparison-sequential/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
