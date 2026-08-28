# CPU vLLM 최적화 적용 및 재측정 계획

이 폴더는 완료된 `baseline`을 변경하지 않고, 같은 모델·Service·100개 prompt·출력 길이·동시성 조건에서 최소 두 가지 최적화를 적용하고 전후 차이를 분석하는 절차를 관리합니다. 실제 배포와 측정 전에 이 문서를 먼저 작성했으며, 실험 결과와 실패한 후보도 이후 같은 문서에 갱신합니다.

## 비교 질문

1. Qwen3.5 native MTP가 Apple M4의 Linux/ARM64 CPU vLLM에서 TPOT와 output throughput을 개선하는가?
2. 베이스라인에서 100%에 도달한 KV cache와 peak running 16 제한을 완화하면 고동시성 처리량 또는 tail latency가 개선되는가?
3. 개선이 단순히 scheduler 대기를 다른 구간으로 이동시킨 결과는 아닌가?
4. MTP draft/verification 또는 더 큰 active batch의 CPU overhead 때문에 오히려 악화되는 지점은 어디인가?

## 고정 조건

다음은 모든 정식 비교에서 변경하지 않습니다.

- 모델/checkpoint: `Qwen/Qwen3.5-0.8B`, revision `2fc06364715b967f1860aea9cf38778875588b17`
- 런타임/image: vLLM `0.26.0+cpu`, `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0`
- Pod CPU request/limit: 4/6 cores
- Pod memory request/limit: 4Gi/6656Mi
- workload: `benchmark/data/prompts.jsonl`의 고정 100건
- 동시성: `1, 2, 5, 10, 20, 50, 100`; 각 단계 총 요청은 항상 100건
- 출력: 요청당 64 tokens, `ignore_eos=true`, `temperature=0`
- warmup/cooldown/metric interval: 단계별 3건 / 3초 / 1초
- Automatic Prefix Caching: off

정식 결과는 설정별 700건입니다. 프롬프트나 출력 길이를 줄이는 사전 기능 검증 수치는 최종 before/after 표에 넣지 않습니다.

## 최적화 1: native MTP

Qwen3.5-0.8B config에는 MTP hidden layer 1개가 포함되어 있습니다. Qwen 공식 vLLM recipe의 시작점은 다음 설정입니다.

```text
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

사용자가 제안한 generic `method=mtp`, speculative tokens 5도 후보로 확인하지만 곧바로 정식 설정으로 가정하지 않습니다. 현재 이미지에는 `qwen3_next_mtp`라는 모델 전용 proposer가 있고 공식 권장 깊이는 2입니다. 먼저 2와 5의 기동 여부, draft acceptance, 짧은 고정 부하를 비교한 후 더 타당한 값을 정식 overlay에 고정합니다.

MTP 판단 지표:

- 우선: TPOT p50/p95, output token/s
- 보조: TTFT/E2E p95, request/s, CPU cores
- MTP 원인 지표: draft tokens, accepted tokens, acceptance rate
- 안전성: memory peak, preemption, OOM/restart

## 최적화 2: KV cache와 scheduler capacity

### FP8 KV cache 후보

vLLM CLI는 `--kv-cache-dtype fp8`을 파싱하지만, 고정 버전의 공식 문서는 FP8 E4M3/E5M2 실행 하드웨어로 CUDA와 ROCm을 명시하고 ARM CPU 지원을 명시하지 않습니다. 따라서 CLI에 선택지가 보인다는 이유만으로 CPU kernel 지원을 가정하지 않습니다.

다음 순서로 검증합니다.

1. 별도 후보 overlay 또는 격리된 기동 검증에서 FP8 KV server 초기화
2. 실패하면 오류 원문과 restart/event를 기록하고 정식 최적화에서 제외
3. 기동해도 20-request 검증에서 출력 정상 완료, memory 감소, token counter 일치를 확인
4. 정확도 평가가 아닌 serving 실험이지만 scale 1.0 사용에 따른 수치 왜곡 가능성도 한계로 기록

### ARM CPU 대안

FP8 KV가 지원되지 않으면 베이스라인 병목에 직접 대응하는 아래 설정을 두 번째 최적화로 사용합니다.

- KV memory: 512MiB → 768MiB
- `max-num-seqs`: 20 → 24
- Pod memory limit과 CPU limit은 그대로 유지

재측정된 베이스라인 peak memory가 6.05GiB였으므로 256MiB의 KV 증가 후에는 6.5GiB limit까지 headroom이 작을 것으로 예상됩니다. 이 설정은 cache dtype을 바꾸지 않으므로 수치 정밀도 변화가 없고, C=20 이상에서 peak running 16을 늘릴 수 있는지 직접 검증할 수 있습니다. 반면 더 큰 batch가 CPU 경쟁을 키우면 TPOT 또는 전체 처리량이 악화될 수 있습니다.

## 실험 행렬

| 이름 | MTP | KV / max sequences | 목적 |
|---|---|---|---|
| `baseline` | off | 512MiB / 20 | 완료된 기준값 |
| `mtp` | 후보 검증 후 고정 | 512MiB / 20 | MTP 효과 단독 분리 |
| `mtp-kv-tuned` | `mtp`와 동일 | 768MiB / 24 | MTP 대비 KV/scheduler 증분 효과 및 두 최적화 결합 결과 |

따라서 `baseline → mtp`로 첫 번째 최적화를, `mtp → mtp-kv-tuned`으로 두 번째 최적화를 분리해 해석할 수 있고, 과제의 최종 before/after는 `baseline → mtp-kv-tuned`으로 제시합니다.

## 배포와 롤백 원칙

- baseline YAML은 수정하지 않고 Kustomize overlay를 추가합니다.
- 각 overlay 배포 후 rendered args, Pod UID/node/restart, startup log의 `speculative_config`, KV capacity를 기록합니다.
- readiness와 smoke test를 통과한 설정만 정식 700건 측정으로 진행합니다.
- 실패한 후보 뒤에는 `make deploy`로 baseline을 복구할 수 있어야 합니다.
- 다음 실험 전에 running/waiting이 0이고 새 Pod가 Ready인지 확인합니다.

예정 명령은 다음과 같습니다.

```bash
make deploy-mtp
make benchmark-mtp

make deploy-mtp-kv-tuned
make benchmark-mtp-kv-tuned

make benchmark-compare
```

## 결과 구조

```text
benchmark/results/
├── baseline/                  # 이미 완료
├── mtp/                       # MTP 단독 700건
├── mtp-kv-tuned/              # 두 최적화 결합 700건
└── comparison/
    ├── comparison.csv
    ├── REPORT.md
    └── charts/
```

FP8 KV 실패 상세는 `reports/03_FAILED_OPTIMIZATION_FP8_KV.md`, 최종 과제 분석은 `reports/04_OPTIMIZATION_FINAL_ANALYSIS.md`에 정리합니다. 최종 문서에는 개선·악화 원인, 효과가 없었던 후보, 로컬 K8s에서 GPU 프로덕션으로 가져갈 수 있는 부분과 재설계할 부분, 다음 최적화 계획을 포함합니다.

## 근거 문서

- Qwen3.5-0.8B model card: <https://huggingface.co/Qwen/Qwen3.5-0.8B>
- Qwen3.5-0.8B config: <https://huggingface.co/Qwen/Qwen3.5-0.8B/raw/main/config.json>
- vLLM speculative decoding: <https://docs.vllm.ai/en/stable/features/speculative_decoding/>
- vLLM quantized KV cache 0.26.0: <https://docs.vllm.ai/en/v0.26.0/features/quantization/quantized_kvcache/>

## 후보 검증 기록

### FP8 KV cache: 적용 불가

- 검증 overlay: `model_serving/k8s/overlays/candidates/kv-fp8`
- 적용 설정: `--kv-cache-dtype fp8 --calculate-kv-scales`
- 결과: 새 Pod `vllm-cpu-5cb7864474-n4r4j`가 Ready가 되지 못하고 exit code 1로 반복 재시작
- 직접 원인: `NotImplementedError: FP8 KV cache on CPU requires x86 with AVX-512 or AMX.`
- 부가 경고: Qwen3.5처럼 recurrent GDN layer가 있는 hybrid model은 runtime KV scale 계산이 신뢰할 수 없어 `calculate_kv_scales`가 강제로 꺼지고 scale 1.0을 사용함
- 판단: Apple M4/aarch64 CPU에서는 FP8 KV kernel이 없어 정식 700건 부하를 실행할 수 없음

즉 `vllm serve --help`에 FP8 선택지가 나타나는 것은 공통 CLI schema가 해당 값을 파싱한다는 뜻이지, 모든 backend가 실행 kernel을 제공한다는 뜻이 아닙니다. 이 후보는 성능이 나쁜 정도가 아니라 현재 장비에서 적용 불가능한 최적화이며, 두 번째 정식 최적화는 위에서 정의한 BF16 KV capacity/scheduler tuning으로 진행합니다.

### Generic MTP, 5 speculative tokens: 기동 성공, 고동시성 후보 탈락

- 검증 overlay: `model_serving/k8s/overlays/candidates/mtp5`
- 적용 설정: `{"method":"mtp","num_speculative_tokens":5}`
- 기동: 성공, smoke test 성공, restart/OOM 0
- vLLM 경고: MTP layer가 1개뿐인 모델에서 2개보다 많은 token을 제안하면 같은 layer를 반복 forward해 acceptance가 낮아질 수 있음
- KV capacity: 512MiB에서 baseline 19,894 → MTP5 5,399 tokens
- pilot: 동일 프롬프트 앞 20건, 64 output tokens, C=1과 C=20; 최종 비교에는 미포함

| C | 성공 | duration | output tok/s | E2E p95 | TTFT p95 | TPOT p50 | peak run/wait | acceptance |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20/20 | 173.52s | 7.38 | 16.63s | 8.94s | 89.87ms | 1/0 | 48.85% |
| 20 | 20/20 | 142.13s | 9.01 | 140.73s | 127.13s | 174.92ms | 3/17 | 48.41% |

C=1에서는 speculative acceptance로 decode가 빨라질 가능성이 확인됐지만, C=20에서는 작은 MTP용 KV capacity 때문에 실제 running이 3으로 제한됐다. baseline 정식 C=20의 13.50 tok/s보다 pilot MTP5의 9.01 tok/s가 낮으므로 `5`는 전체 동시성 범위를 위한 정식 후보에서 제외하고, Qwen 공식 recipe의 model-specific `qwen3_next_mtp`, 2 tokens를 다음 pilot으로 비교합니다.

### Qwen 전용 MTP, 2 speculative tokens: 정식 설정으로 선택

- 검증 overlay: `model_serving/k8s/overlays/mtp`
- 설정: `{"method":"qwen3_next_mtp","num_speculative_tokens":2}`
- 기동/안전성: smoke 성공, restart/OOM 0
- KV capacity: 512MiB에서 9,137 tokens

| C | 성공 | duration | output tok/s | E2E p95 | TTFT p95 | TPOT p50 | peak run/wait | acceptance |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20/20 | 167.47s | 7.64 | 15.88s | 9.65s | 75.51ms | 1/0 | 71.89% |
| 20 | 20/20 | 115.04s | 11.13 | 112.68s | 103.46s | 377.90ms | 5/15 | 66.73% |

동일 pilot에서 MTP2는 MTP5보다 C=1 duration 3.5%, C=20 duration 19.1%가 짧았고 acceptance는 약 18~23%p 높았다. C=20 output throughput도 23.5% 높았다. MTP2의 TPOT p50이 C=20에서 더 높은 것은 KV capacity 증가로 실제 running이 3에서 5로 늘어 decode batch의 CPU 경쟁이 커진 영향으로 해석할 수 있다. 그러나 전체 처리량과 E2E p95가 개선됐으므로 공식 MTP2를 정식 700건 설정으로 선택한다.

### MTP2 + 768MiB KV / 24 sequences: 정식 결합 설정으로 선택

- 검증 overlay: `model_serving/k8s/overlays/mtp-kv-tuned`
- MTP는 위의 정식 MTP2와 동일
- KV capacity: 512MiB 9,137 → 768MiB 13,705 tokens, 50% 증가
- C=20 pilot: 동일 앞 20건·64 output tokens

| 설정 | 성공 | duration | output tok/s | E2E p95 | TTFT p95 | TPOT p50 | peak run/wait | peak RAM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MTP2 | 20/20 | 115.04s | 11.13 | 112.68s | 103.46s | 377.90ms | 5/15 | 6.03GiB |
| MTP2+KV | 20/20 | 98.09s | 13.05 | 97.20s | 86.36s | 468.98ms | 8/12 | 6.27GiB |

KV tuning은 MTP 단독 대비 output throughput을 17.3% 높이고 E2E p95를 13.7% 낮췄다. peak running이 5에서 8로 늘면서 waiting이 줄었기 때문이다. 반면 더 큰 active batch가 같은 6-core CPU를 나눠 사용해 TPOT p50은 24.1% 악화됐다. peak memory는 6.27GiB로 6.5GiB limit 안이었고 OOM/restart는 0이므로 이 trade-off를 정식 700건에서 재검증한다.

## 정식 2,100-request 비교 결과

세 설정에서 각 700건을 완료했다. 총 2,100/2,100 성공, client/server token counter 전 phase 일치, OOM/restart와 prefix hit는 0이다.

| C | Baseline output tok/s | MTP2 | MTP2+KV | 결합 vs baseline |
|---:|---:|---:|---:|---:|
| 1 | 5.16 | 7.80 | 7.43 | +44.0% |
| 2 | 7.64 | 9.99 | 10.01 | +31.0% |
| 5 | 11.28 | 11.87 | 11.40 | +1.1% |
| 10 | 12.06 | 11.81 | 11.51 | -4.6% |
| 20 | 13.50 | 11.78 | 11.84 | -12.3% |
| 50 | 13.46 | 12.31 | 12.52 | -7.0% |
| 100 | 13.54 | 12.05 | 12.29 | -9.2% |

MTP2의 약 75~77% acceptance는 낮은 동시성의 decode를 크게 개선했다. 그러나 512MiB KV에서 active running이 5로 제한돼 C≥20 총 처리량은 baseline보다 낮았다. 768MiB KV는 running을 8로 늘리고 waiting을 3씩 줄였지만, 6-core CPU에서 batch 경쟁을 키워 MTP 단독 대비 C=10~100 TPOT p95가 46.8~76.7% 악화됐다. 따라서 저동시성에는 MTP2, 지속적인 C≥10 처리량에는 baseline이 이 장비의 더 나은 선택이며 768MiB/24-seq 결합 설정은 범용 기본값으로 채택하지 않는다.

자동 수치표와 그래프는 [`benchmark/results/comparison`](../benchmark/results/comparison/), 상세 원인·실패 후보·GPU production 전환 분석은 [`reports/04_OPTIMIZATION_FINAL_ANALYSIS.md`](../reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)에 있다.

이후 baseline에서 CPU limit만 `6 → 8`로 바꾼 독립 실험은 [`optimization/cpu8/README.md`](cpu8/README.md)와 [`reports/05_BASELINE_CPU8_ANALYSIS.md`](../reports/05_BASELINE_CPU8_ANALYSIS.md)에 분리했다.

CPU limit 8을 고정한 후속 baseline/MTP/MTP+KV 비교는 [`optimization/cpu8-mtp-kv/README.md`](cpu8-mtp-kv/README.md)와 [`reports/06_CPU8_MTP_KV_ANALYSIS.md`](../reports/06_CPU8_MTP_KV_ANALYSIS.md)에 분리했다.
