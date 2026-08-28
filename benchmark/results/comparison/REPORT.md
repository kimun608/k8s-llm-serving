# Baseline vs MTP vs capacity bundle 자동 비교

## 검증

- 비교 요청: `2100`건, 실패 `0`건
- 세 설정의 prompt file SHA-256, 모델, 100건, 출력 64 tokens, 동시성, sampling, warmup/cooldown가 동일함
- client/server prompt와 generation token counter가 모든 단계에서 일치함
- 정식 phase의 UTC wall clock과 monotonic timer 오차가 1%/5초 이내이며 metric scrape error가 없음
- 전체 OOM kill 증가량: `0`

`mtp-kv-tuned`은 역사적인 artifact ID다. 실제 변경은 KV `512→768MiB`와 `max-num-seqs 20→24`를 함께 적용한 capacity bundle이며 KV-only 실험이 아니다.

## 결과

| C | Baseline / MTP / Bundle output tok/s | Bundle vs base | Baseline / Bundle E2E p95 | Bundle vs base | Base / MTP / Bundle peak wait | Bundle acceptance |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5.16 / 7.80 / 7.43 | +44.0% | 19.00s / 15.36s | -19.2% | 0 / 0 / 0 | 76.7% |
| 2 | 7.64 / 9.99 / 10.01 | +31.0% | 22.32s / 19.25s | -13.8% | 0 / 0 / 0 | 76.1% |
| 5 | 11.28 / 11.87 / 11.40 | +1.1% | 38.92s / 37.73s | -3.1% | 0 / 0 / 0 | 74.8% |
| 10 | 12.06 / 11.81 / 11.51 | -4.6% | 66.80s / 71.46s | +7.0% | 1 / 5 / 2 | 76.2% |
| 20 | 13.50 / 11.78 / 11.84 | -12.3% | 131.17s / 127.53s | -2.8% | 11 / 15 / 12 | 75.9% |
| 50 | 13.46 / 12.31 / 12.52 | -7.0% | 254.46s / 261.42s | +2.7% | 40 / 45 / 42 | 75.7% |
| 100 | 13.54 / 12.05 / 12.29 | -9.2% | 464.06s / 510.03s | +9.9% | 91 / 95 / 92 | 76.7% |

## 그래프

- [Output throughput](charts/output-token-throughput.svg)
- [E2E p95](charts/e2e-p95.svg)
- [TTFT p95](charts/ttft-p95.svg)
- [TPOT p95](charts/tpot-p95.svg)
- [Peak running](charts/peak-running.svg)
- [Peak waiting](charts/peak-waiting.svg)
- [KV cache](charts/kv-cache.svg)
- [Pod memory](charts/pod-memory.svg)
- [Pod CPU](charts/pod-cpu.svg)
- [MTP acceptance](charts/mtp-acceptance.svg)

이 문서는 원시 summary에서 자동 생성한 사실표다. 개선·악화 원인, FP8 실패, GPU 프로덕션 전환 판단은 [최종 분석 리포트](../../../reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)에 별도로 서술한다.
