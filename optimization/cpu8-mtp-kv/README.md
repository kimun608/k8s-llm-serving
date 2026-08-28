# CPU limit 8 고정: Baseline vs MTP vs MTP+KV 비교

이 문서는 배포와 측정 전에 작성한 CPU 8 최적화 실험 계획이다. 기존 `baseline-cpu8`을 기준으로 CPU request/limit과 memory를 고정하고, native MTP를 단독 적용한 뒤 KV/scheduler capacity를 추가 적용한다.

## 비교 질문

1. 6-core에서 저동시성 위주로 효과가 있었던 Qwen native MTP가 8-core에서도 output throughput과 TPOT를 개선하는가?
2. MTP가 사용하는 KV state 때문에 줄어든 active sequence capacity를 KV 768MiB와 max sequences 24로 완화하면 고동시성 queue와 처리량이 개선되는가?
3. 추가 CPU가 MTP verification과 더 큰 active batch의 비용을 감당해 기존 6-core 결과와 다른 결론을 만드는가?

## 실험 행렬

| 이름 | CPU limit | MTP | KV / max sequences | 비교 목적 |
|---|---:|---|---|---|
| `baseline-cpu8` | 8 | off | 512MiB / 20 | 완료된 CPU 8 기준값 |
| `mtp-cpu8` | 8 | `qwen3_next_mtp`, 2 tokens | 512MiB / 20 | MTP 단독 효과 |
| `mtp-kv-tuned-cpu8` | 8 | 위와 동일 | 768MiB / 24 | MTP 대비 KV/scheduler 증분 효과 |

여기서 KV 실험은 FP8 KV dtype이 아니다. Apple M4/ARM64에서는 vLLM FP8 KV CPU kernel이 지원되지 않아 이미 기동 실패를 확인했다. 이번에는 BF16 KV dtype을 유지하고 cache byte 예산과 scheduler capacity만 늘린다. 따라서 다음 두 구간을 분리해 해석한다.

- `baseline-cpu8 → mtp-cpu8`: 최적화 1, native MTP 효과
- `mtp-cpu8 → mtp-kv-tuned-cpu8`: 최적화 2, KV/scheduler capacity 증분 효과
- `baseline-cpu8 → mtp-kv-tuned-cpu8`: 최종 결합 효과

## 모든 설정에서 고정할 조건

- Host/Docker: Apple M4, Docker Desktop 10 vCPU / 약 7.65GiB
- Runtime/image/model: vLLM `0.26.0+cpu`, 동일 image와 Qwen3.5-0.8B checkpoint
- Kubernetes CPU request/limit: `4/8`
- Memory request/limit: `4Gi/6656Mi`
- text-only, BF16, max context 2,048
- Automatic Prefix Caching off
- 고정 prompt 100개와 SHA-256, prompt 순서
- 동시성 `1, 2, 5, 10, 20, 50, 100`; C별 요청 100건
- streaming, output 64 tokens, `ignore_eos=true`, temperature 0
- phase별 warmup 3건, cooldown 3초, metric interval 1초

설정별 정식 측정은 700건이고 세 설정의 비교 요청은 총 2,100건이다. 이미 완료된 `baseline-cpu8` 700건은 재사용하고, MTP 및 MTP+KV 두 설정 1,400건을 새로 실행한다.

## 변경점

### MTP 단독

```text
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

CPU 6 실험에서 acceptance가 약 75~77%였던 모델 전용 설정을 그대로 사용한다. generic MTP 5-token 후보는 acceptance가 낮고 KV capacity가 작아 이미 탈락했으므로 재시험하지 않는다.

### MTP+KV tuned

```diff
--- mtp-cpu8
+++ mtp-kv-tuned-cpu8
- --max-num-seqs 20
+ --max-num-seqs 24
- --kv-cache-memory-bytes 536870912
+ --kv-cache-memory-bytes 805306368
```

MTP config와 CPU limit 8은 그대로 유지한다. memory limit 6.5GiB는 변경하지 않으므로 startup, peak RAM, cgroup memory events와 OOM/restart를 먼저 확인한다.

## 지표와 판정

- 정확성: 700/700 success, client/server prompt·generation token counter 일치
- 처리량: request/s, prompt/output token/s
- 사용자 지연: E2E·TTFT·TPOT p50/p95/p99
- MTP: draft/accepted tokens와 acceptance rate
- scheduler/KV: running, waiting, peak KV, preemption
- 자원/안전성: Pod CPU, peak RAM, OOM kill, restart, metric scrape error

throughput 증가만으로 채택하지 않는다. TTFT가 악화되거나 waiting이 증가하면 queue 이동을 확인하고, TPOT와 CPU가 함께 악화되면 speculative verification 또는 active batch 경쟁으로 해석한다. MTP+KV가 MTP보다 좋아도 baseline-cpu8보다 나쁘면 범용 기본값으로 채택하지 않는다.

## 실행 순서

```bash
make deploy-mtp-cpu8
make smoke
make benchmark-mtp-cpu8

make deploy-mtp-kv-tuned-cpu8
make smoke
make benchmark-mtp-kv-tuned-cpu8

make benchmark-compare-cpu8-optimizations
```

## 결과 위치

```text
benchmark/results/
├── baseline-cpu8/
├── mtp-cpu8/
├── mtp-kv-tuned-cpu8/
└── comparison-cpu8-optimizations/
```

## 실측 결과

세 설정의 정식 요청 `2,100/2,100`건이 성공했고 OOM kill, Pod restart, metric scrape error는 0이었다.

| C | Baseline CPU8 | MTP CPU8 | MTP+KV CPU8 | MTP vs base | KV vs MTP |
|---:|---:|---:|---:|---:|---:|
| 1 | 6.44 | 8.24 | 9.33 | +27.8% | +13.3% |
| 2 | 9.28 | 10.30 | 12.10 | +11.0% | +17.4% |
| 5 | 13.16 | 14.38 | 14.35 | +9.3% | -0.3% |
| 10 | 14.94 | 14.41 | 14.83 | -3.5% | +2.9% |
| 20 | 16.22 | 14.62 | 14.75 | -9.9% | +0.9% |
| 50 | 15.03 | 14.89 | 14.33 | -0.9% | -3.7% |
| 100 | 15.15 | 15.18 | 13.66 | +0.2% | -10.0% |

단위는 output token/s다. MTP acceptance는 약 75~77%였고, KV 증설은 peak running을 5에서 8로 늘리고 waiting을 3개 줄였다. 하지만 같은 8-core CPU에서 더 큰 active batch가 경쟁해 C=50·100 처리량은 오히려 낮아졌다. C=1·2에서 KV 증설 후 나타난 큰 차이는 KV 사용량이 낮은 구간이므로 KV의 인과 효과가 아니라 단일 반복의 host/JIT/thermal 변동 가능성이 크다.

최종 판단은 **C≤5 interactive 후보는 `mtp-cpu8`, 지속적인 C≥10 또는 혼합 부하의 기본값은 `baseline-cpu8`**이다. `mtp-kv-tuned-cpu8`은 6.34GiB까지 메모리를 사용하면서 고동시성 처리량이 악화돼 범용 기본값으로 채택하지 않는다.

전체 지표, 원인, FP8 실패 이력과 production 전환 분석은 [CPU8 MTP·KV 분석 리포트](../../reports/06_CPU8_MTP_KV_ANALYSIS.md), 자동 생성 원표와 그래프는 [comparison-cpu8-optimizations](../../benchmark/results/comparison-cpu8-optimizations/)를 본다.
