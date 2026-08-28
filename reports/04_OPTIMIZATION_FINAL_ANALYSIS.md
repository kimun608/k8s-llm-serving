# 4. CPU vLLM 최적화 적용 및 최종 분석

## 결론

Qwen3.5-0.8B의 native MTP와 KV/scheduler capacity 조정을 실제 Kind worker에 적용하고, baseline과 완전히 같은 100개 prompt를 동시성 `1, 2, 5, 10, 20, 50, 100`에서 각각 실행했다. 정식 비교는 설정당 700건, 총 2,100건이며 전부 성공했다. 모든 phase에서 client/server prompt·generation token 수가 일치했고 OOM kill과 prefix cache hit는 0이었다.

결과는 부하 영역에 따라 갈렸다.

- MTP2는 C=1과 2에서 output throughput을 각각 51.1%, 30.7% 높였다. C=1 TPOT p95도 40.3% 줄었다.
- C=20 이상에서는 MTP가 차지하는 KV/cache 및 verification 비용 때문에 baseline 대비 output throughput이 8.6~12.7% 낮았다.
- KV를 512MiB에서 768MiB로 늘리면 MTP 환경의 peak running이 5에서 8로 증가하고 peak waiting은 3개씩 줄었다. 그러나 같은 6-core CPU에서 더 큰 active batch를 실행해 MTP 단독 대비 TPOT p95가 C=10~100에서 46.8~76.7% 악화됐다.
- 두 최적화를 결합한 설정은 baseline 대비 C=1·2에서 유리하지만 C=10·20·50·100의 output throughput은 4.6~12.3% 낮다. 따라서 이 장비에서는 결합 설정을 모든 부하의 단일 정답으로 채택할 수 없다.
- 운영 선택은 저동시성·interactive 요청에는 MTP2, 지속적인 C≥10 처리량에는 baseline이 타당하다. 768MiB KV/24 sequences 설정은 waiting을 조금 줄였지만 6-core 환경의 기본값으로는 권장하지 않는다.

7개 phase의 시간을 단순 합산하면 baseline은 4,598.07초, MTP는 4,137.20초, 결합 설정은 4,190.49초였다. 동일한 총 44,800 output tokens 기준 합산 처리량은 각각 9.74, 10.83, 10.69 token/s다. 이 합산치는 저동시성 phase의 긴 실행 시간을 포함한 실험 전체 비용이며, 특정 운영 동시성의 capacity를 대신하지 않는다.

baseline의 초기 C=2 표본에는 host 중단이 있어 원시 자료를 보존하고 같은 100건으로 재측정했다. 위 수치와 자동 비교표는 중단 없는 재측정 baseline을 사용한다. 제외·재측정 기준과 증거는 [CPU 8 단일 변경 리포트](05_BASELINE_CPU8_ANALYSIS.md)의 데이터 유효성 절에 함께 기록했다.

## 장비·모델·런타임 선택 근거

- Host: Apple M4, logical CPU 10개, RAM 16GiB
- Docker Desktop VM: 10 vCPU, 7.65GiB, Linux/ARM64
- Pod limit: CPU 6 cores, memory 6.5GiB
- Model: `Qwen/Qwen3.5-0.8B`, revision `2fc06364715b967f1860aea9cf38778875588b17`
- Runtime/image: vLLM `0.26.0+cpu`, `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0`

0.8B 모델은 제한된 Docker VM 메모리에서 BF16 weights, 런타임, KV cache를 함께 수용할 수 있다. 또한 checkpoint config에 native MTP layer가 있어 모델을 바꾸지 않고 speculative decoding on/off를 비교할 수 있다. 동일 모델 revision과 이미지를 모든 정식 실험에 고정했기 때문에 모델 품질·weight 차이를 서빙 최적화 효과로 오인하지 않는다.

## 실험 설계와 고정 조건

| 항목 | 고정값 |
|---|---|
| Workload | GSM8K, HumanEval, TruthfulQA, LongBench Qasper 각 25건, 총 100건 |
| 동시성 | C=`1, 2, 5, 10, 20, 50, 100`; 각 C에서 총 요청은 항상 100건 |
| API | OpenAI-compatible streaming chat completions |
| 출력 | 요청당 정확히 64 tokens, `ignore_eos=true` |
| Sampling | `temperature=0`, seed `20260828` |
| Context | max model length 2,048 tokens |
| Warmup/cooldown | C별 3건(통계 제외), idle 확인 후 3초 |
| Prefix reuse | Automatic Prefix Caching off; 측정 prefix hit 0 |
| Resources | CPU request/limit 4/6, memory request/limit 4Gi/6656Mi |

각 설정의 100건을 C회 반복한 것이 아니다. 동일한 100건 중 최대 C건만 동시에 in-flight가 되는 closed-loop 방식이다. phase 사이에는 모든 running/waiting 요청이 0이 될 때까지 기다렸다. 일반 autoregressive KV cache는 추론에 필요한 상태이므로 유지하고, 요청 간 prefix 재사용만 껐다.

## 적용한 설정

| 설정 | Speculative decoding | KV / max sequences | 기동 시 KV capacity |
|---|---|---|---:|
| `baseline` | off | 512MiB / 20 | 19,894 tokens |
| `mtp` | `qwen3_next_mtp`, 2 tokens | 512MiB / 20 | 9,137 tokens |
| `mtp-kv-tuned` | 위와 동일 | 768MiB / 24 | 13,705 tokens |

첫 번째 최적화는 Qwen 공식 recipe에 맞춘 native MTP다. 사용자가 처음 제안한 generic `method=mtp`, 5 tokens도 실제로 기동·pilot 측정했지만 draft acceptance가 약 48%이고 C=20 output throughput이 9.01 token/s에 그쳐, acceptance 약 67~72%인 model-specific MTP2를 정식 설정으로 선택했다.

두 번째 최적화는 BF16 KV byte 예산과 scheduler sequence limit의 동시 조정이다. 처음 후보였던 FP8 KV는 현재 Apple M4/ARM64 CPU kernel에서 지원되지 않아 server가 초기화되지 않았다. 이 실패는 [03_FAILED_OPTIMIZATION_FP8_KV.md](03_FAILED_OPTIMIZATION_FP8_KV.md)에 예외 원문과 복구 절차까지 별도로 기록했다.

## 지표를 선택한 이유

| 관점 | 지표 | 판단 목적 |
|---|---|---|
| 정확성·안전성 | success, client/server token counter, OOM/restart | 빠르더라도 실패·누락·재시작이 있으면 개선으로 보지 않음 |
| 사용자 체감 | E2E p50/p95/p99 | 요청 전체 대기시간 |
| Prefill/queue | TTFT p50/p95/p99 | 입력 처리와 scheduler waiting의 영향을 분리 |
| Decode | TPOT p50/p95/p99 | 첫 token 뒤 token 생성 간격과 CPU batch 경쟁 관찰 |
| Capacity | request/s, output token/s | 일정 시간에 실제 완료한 요청·token 양 |
| 원인 | running, waiting, KV usage, preemption | scheduler/cache 병목과 처리량 변화 연결 |
| 자원 | Pod cgroup CPU/RAM | CPU 포화, memory headroom, OOM 위험 확인 |
| MTP | drafted/accepted tokens, acceptance | speculative overhead와 유효 제안 비율 확인 |

평균만으로 tail을 숨기지 않기 위해 latency는 p95를 중심으로 해석한다. 다만 E2E p95, TTFT p95, TPOT p95는 서로 다른 요청이 각 percentile에 위치할 수 있어 수학적으로 더해서는 안 된다.

## Before/after 실측

아래 `Combined`는 MTP2와 768MiB KV/24 sequences를 모두 적용한 결과다. `↓`가 항상 좋은 것은 아니므로 변화율은 metric 의미에 따라 읽어야 한다. throughput은 증가가 좋고 latency는 감소가 좋다.

| C | Output tok/s baseline → combined | 변화 | E2E p95 변화 | TTFT p95 변화 | TPOT p95 변화 | Peak run/wait baseline → combined |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5.16 → 7.43 | +44.0% | -19.2% | +1.9% | -36.3% | 1/0 → 1/0 |
| 2 | 7.64 → 10.01 | +31.0% | -13.8% | -12.9% | -14.4% | 2/0 → 2/0 |
| 5 | 11.28 → 11.40 | +1.1% | -3.1% | -58.1% | +11.0% | 5/0 → 5/0 |
| 10 | 12.06 → 11.51 | -4.6% | +7.0% | -39.8% | +7.4% | 10/1 → 8/2 |
| 20 | 13.50 → 11.84 | -12.3% | -2.8% | +14.4% | -21.4% | 16/11 → 8/12 |
| 50 | 13.46 → 12.52 | -7.0% | +2.7% | +8.9% | -29.7% | 16/40 → 8/42 |
| 100 | 13.54 → 12.29 | -9.2% | +9.9% | +12.7% | -36.8% | 16/91 → 8/92 |

자동 생성된 전체 수치표와 그래프는 [comparison/REPORT.md](../benchmark/results/comparison/REPORT.md) 및 [comparison.csv](../benchmark/results/comparison/comparison.csv)에 있다.

## 왜 개선되거나 악화됐는가

### C=1~2: MTP decode 이득

동시에 실행하는 sequence가 적을 때 baseline은 CPU memory-bound decode를 한 token씩 반복한다. MTP2는 acceptance 약 76%로 다음 token 두 개 중 상당수를 한 번의 target verification에서 수용했다. 그 결과 C=1 output throughput은 51.1%, C=2는 30.7% 증가했다. KV 증설은 이 영역에서 사용되지 않으므로 결합 설정은 MTP 단독 대비 C=1 처리량이 4.7% 낮고 C=2는 0.2% 높은 정도였다. 이 차이는 설정 이득보다는 단일 반복의 host background load와 thermal 변동 범위로 보는 것이 안전하다.

### C=5~10: MTP용 KV capacity와 CPU batch 경쟁이 교차

MTP는 draft state까지 저장해 같은 512MiB에서 KV capacity가 baseline의 19,894에서 9,137 tokens로 줄었다. MTP 단독은 C=5부터 peak KV 91.2%, C=10부터 peak running 5와 waiting 5를 기록했다. 768MiB로 늘리면 peak running이 8로 늘고 C=10 waiting은 5에서 2로 줄어 TTFT p95는 MTP 단독 대비 33.1% 개선됐다.

하지만 8개 active sequence가 6 CPU cores를 나누고 MTP draft/verification까지 수행하면서 C=10 TPOT p95는 MTP 단독보다 76.7% 나빠졌다. 결과적으로 E2E p95는 12.9%, output throughput은 2.6% 악화됐다. 즉 queue 일부를 실행 단계로 옮겼을 뿐 총 compute capacity가 늘지는 않았다.

### C=20~100: baseline의 더 큰 active batch가 총 처리량 우세

baseline은 peak running 16인 반면 MTP 단독은 5, 결합 설정은 8이었다. 결합 설정은 MTP 단독보다 waiting을 각 고동시성 구간에서 3개 줄이고 output throughput을 C=20/50/100에서 0.5%/1.7%/2.0% 높였다. 그러나 baseline보다 active batch가 절반이고 speculative verification 비용도 있어 output throughput은 7.0~12.3% 낮았다.

MTP의 고동시성 TPOT p95가 baseline보다 낮은데 총 처리량도 낮은 것은 모순이 아니다. MTP 단독은 동시에 5개만 decode하므로 실행 중인 개별 요청은 더 빠르게 token을 받지만 더 많은 요청이 first token 전에 queue에서 기다린다. 그 결과 C=50·100 TTFT p95와 E2E p95가 baseline보다 악화됐다. 결합 설정은 running 8로 늘어 MTP 단독보다 queue를 줄였지만, 개별 TPOT를 다시 악화시키는 trade-off가 나타났다.

평균 Pod CPU는 세 설정 모두 대부분 5.9~6.0 cores로 limit에 포화됐다. KV를 늘려도 CPU가 늘지 않으므로 고동시성 총 처리량 개선 폭이 작았던 근본 이유다. MTP acceptance는 KV 증설 전후 약 75~77%로 안정적이어서, 결합 설정의 악화는 acceptance 하락이 아니라 active batch/CPU 경쟁 때문이다.

### 메모리와 안정성

- 최대 Pod RAM: baseline 6.05GiB, MTP 6.14GiB, 결합 6.29GiB
- Pod limit: 6.5GiB
- OOM kill/restart: 모든 정식 phase 0
- Preemption: baseline 총 2, MTP와 결합 설정 0
- Prefix cache hit: 모든 정식 phase 0

결합 설정은 기능적으로 안전하게 완주했지만 peak와 limit 사이가 약 0.21GiB뿐이다. 로컬 재현에는 충분했으나 production headroom으로는 부족하다. preemption 제거는 긍정적이지만 처리량 손실을 상쇄하지 못했다.

## 효과가 없거나 실패한 최적화

### FP8 KV cache: 현재 장비에서 적용 불가

`--kv-cache-dtype fp8 --calculate-kv-scales`를 실제 배포했으나 다음 예외로 Pod가 Ready가 되지 않았다.

```text
NotImplementedError: FP8 KV cache on CPU requires x86 with AVX-512 or AMX.
```

공통 CLI가 값을 파싱하는 것과 backend kernel 지원은 다르다. Apple M4/ARM64에는 vLLM 0.26.0의 해당 kernel이 없었다. 또한 Qwen3.5의 hybrid GDN layer 때문에 runtime KV scale 계산도 강제로 비활성화됐다. 따라서 실패 요청 700건을 만드는 대신 startup failure를 기록하고 baseline으로 복구했다.

### Generic MTP 5 tokens: 기동하지만 후보 탈락

모델에는 MTP layer가 1개뿐이라 5-token proposal은 같은 layer를 반복 사용한다. pilot acceptance는 약 48%로 MTP2보다 18~23%p 낮았고, C=20 output throughput도 9.01 token/s였다. “더 많이 예측하면 더 빠르다”는 가설이 낮은 acceptance와 더 작은 KV capacity 때문에 성립하지 않았다.

### KV 768MiB / 24 sequences: 부분 효과, 전체 기본값으로는 실패

pilot 20건에서는 MTP 단독 대비 output throughput이 17.3% 개선됐지만 정식 100건 C=20에서는 0.5%에 그쳤다. 정식 C=10에서는 오히려 2.6% 악화됐다. prompt 길이 전체 분포와 지속 시간이 포함되자 더 큰 active batch의 CPU 경쟁이 드러난 것이다. 짧은 pilot은 기능 검증과 후보 제거에는 유용하지만 성능 결론으로 사용하면 안 된다.

## 로컬 K8s에서 GPU production으로 가져갈 것

### 그대로 유효한 원칙

- 모델 revision, runtime image, Kubernetes version, workload SHA-256을 고정하는 재현성
- container image build, registry/load, Deployment, Service, readiness/liveness의 책임 분리
- baseline을 보존하고 Kustomize overlay로 실험 설정을 분리하는 방식
- 동일 request set과 output tokens로 before/after를 비교하고 client/server counter를 교차 검증하는 방식
- E2E·TTFT·TPOT·throughput과 scheduler/KV/resource metric을 함께 보는 분석 원칙
- 실패한 최적화도 startup log, event, rollback과 함께 기록하는 변경 관리

### 다시 설계할 부분

| 영역 | 현재 로컬 구성 | GPU production 재설계 |
|---|---|---|
| Runtime/image | ARM64 CPU image | CUDA/ROCm, driver와 vLLM compatibility가 검증된 image, GPU별 kernel/quantization 검증 |
| Scheduling | 단일 worker, CPU nodeSelector | GPU Operator/device plugin, accelerator label·taint/toleration, topology 및 MIG 정책 |
| Parallelism | 단일 replica·단일 process | tensor/pipeline/data parallel 조합, NVLink/PCIe/NCCL topology, model별 replica sizing |
| Availability | `Recreate`, worker 1개 | RollingUpdate, 다중 replica/AZ, anti-affinity, PDB, drain·node failure 검증 |
| Autoscaling | 없음 | CPU HPA가 아니라 queue depth, waiting, TTFT, KV pressure, request rate 기반 custom autoscaling |
| Model 배포 | image에 model 포함 | registry/object storage, local NVMe cache, startup prefetch, image와 weight lifecycle 분리 |
| Networking/security | ClusterIP와 port-forward | Gateway/Ingress, TLS, auth, quota/rate limit, network policy |
| Observability | 실험 중 파일 수집 | Prometheus/Grafana, 중앙 로그, tracing, SLO·alert와 장기 capacity trend |
| Quantization | BF16, FP8 startup 검증 | target GPU의 FP8/INT8 kernel, calibrated scale, perplexity/task 품질 회귀까지 포함 |

현재 optional HPA는 수행하지 않았다. 6.29GiB peak Pod를 Docker VM 7.65GiB에서 두 개로 scale-out할 수 없어 HPA 동작 검증이 OOM 또는 Pending으로 왜곡되기 때문이다. worker 강제 중단도 현재 worker가 하나뿐이고 Pod에 worker nodeSelector가 있어 “다른 worker로 재스케줄”될 대상이 없다. 선택 과제를 의미 있게 수행하려면 Docker memory를 늘리고 Kind worker를 최소 두 개로 재생성한 뒤 replica/HPA 및 node failure를 검증해야 한다.

## 시간이 더 있다면 다음으로 시도할 것

1. 각 설정을 최소 3회 교차 순서로 반복해 중앙값과 변동 폭을 제시한다. 현재 단일 반복에는 thermal/background load 영향이 남아 있다.
2. MTP speculative tokens를 1과 2에서 prompt 길이·동시성별로 비교하고, acceptance와 queue depth에 따라 MTP/non-MTP replica로 라우팅한다.
3. `max-num-seqs`, KV bytes, `max-num-batched-tokens`를 작은 grid로 탐색한다. 목표는 단순 running 최대화가 아니라 SLO를 만족하는 throughput 최대화다.
4. 반복 system prompt가 있는 실제 workload에서는 APC를 별도 A/B 실험한다. 이번 워크로드는 객관적 cold-prefix 비교를 위해 APC를 의도적으로 껐다.
5. 지원 x86 CPU에서 oneDNN/IPEX와 weight INT8/INT4를 비교하고, 처리량뿐 아니라 task 품질 회귀를 측정한다.
6. GPU production에서는 chunked prefill, prefix-aware routing, tensor parallel, disaggregated prefill/decode를 prompt 길이와 TTFT SLO에 맞춰 검증한다.

## 재현 명령과 산출물

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-results.XXXXXX)"

make deploy
make benchmark-baseline RESULTS_ROOT="$rerun_root"

make deploy-mtp
make benchmark-mtp RESULTS_ROOT="$rerun_root"

make deploy-mtp-kv-tuned
make benchmark-mtp-kv-tuned RESULTS_ROOT="$rerun_root"

make benchmark-compare RESULTS_ROOT="$rerun_root"
```

- MTP raw/summary/report: [`benchmark/results/mtp`](../benchmark/results/mtp/)
- 결합 raw/summary/report: [`benchmark/results/mtp-kv-tuned`](../benchmark/results/mtp-kv-tuned/)
- 자동 비교 CSV/그래프: [`benchmark/results/comparison`](../benchmark/results/comparison/)
- 최적화 설계·pilot 기록: [`optimization/README.md`](../optimization/README.md)
- FP8 실패 상세: [`reports/03_FAILED_OPTIMIZATION_FP8_KV.md`](03_FAILED_OPTIMIZATION_FP8_KV.md)

## 참고 문서

- Qwen3.5-0.8B model card: <https://huggingface.co/Qwen/Qwen3.5-0.8B>
- Qwen3.5-0.8B config: <https://huggingface.co/Qwen/Qwen3.5-0.8B/raw/main/config.json>
- vLLM speculative decoding: <https://docs.vllm.ai/en/stable/features/speculative_decoding/>
- vLLM 0.26.0 quantized KV cache: <https://docs.vllm.ai/en/v0.26.0/features/quantization/quantized_kvcache/>
