# CPU vLLM 부하 측정 자동 리포트: baseline-cpu8

## 검증 요약

- 완료 요청: `100/100`
- 동시성: `5`; 각 단계의 prompt 100건과 출력 64 tokens는 동일함
- 최고 output throughput: C=`5`, `68.83 token/s`
- 최초 scheduler waiting: C=`없음`
- 전체 prefix hit / preemption / OOM kill 증가량: `0 / 0 / 0`
- MTP draft acceptance 범위: `N/A`
- 최대 peak running / waiting / KV / RAM: `5 / 0 / 32.8% / 5.82GiB`

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100.0% | 1.075 | 68.83 | 4.43 / 5.60 | 1.45 / 2.69 | 46.04 / 68.72 | 0 | 32.8% | 7.86 | 5.82GiB |

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

이 문서는 해당 설정의 원시 요청과 1초 metric 시계열에서 자동 생성한 사실표다. 8개 설정이 모두 끝난 뒤 [동일 결과 루트의 종합 비교](../../comparison-all/REPORT.md)에서 baseline 대비 직접 효과를 교차 분석한다.
