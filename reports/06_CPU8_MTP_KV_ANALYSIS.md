# CPU limit 8 고정: MTP와 capacity bundle 분석

> 이 문서는 기존 세 설정의 역사적 분석이다. 이후 KV-only와 `max-num-seqs`-only를 각각 700건 추가해 혼합 변수를 분리했으며, 최종 결론은 [최종 종합 분석](07_FINAL_COMPREHENSIVE_ANALYSIS.md)을 따른다.

## 결론

CPU limit을 `8`로 고정한 상태에서 `baseline-cpu8`, `mtp-cpu8`, `mtp-kv-tuned-cpu8`을 동일한 100개 prompt와 동시성 `1, 2, 5, 10, 20, 50, 100`으로 비교했다. 설정별 700건, 총 2,100건이 모두 성공했고 client/server token counter, wall clock, metric scrape, OOM을 자동 검증했다.

결과는 부하 영역에 따라 갈렸다.

- MTP 단독은 C=1·2·5 output throughput을 baseline-cpu8보다 각각 `27.8%`, `11.0%`, `9.3%` 높였다.
- MTP 단독은 C=10·20에서 각각 `3.5%`, `9.9%` 낮았고, C=50·100은 `-0.9%`, `+0.2%`로 사실상 동률이었다.
- KV를 `512→768MiB`, `max-num-seqs`를 `20→24`로 **동시에** 늘린 capacity bundle은 MTP 환경의 peak running을 고동시성에서 `5→8`로 늘리고 peak waiting을 3개 줄였다. 그러나 C=50·100 output throughput은 MTP 단독보다 각각 `3.7%`, `10.0%` 낮아졌다.
- 결합 설정은 baseline-cpu8 대비 C=1·2·5에서 `44.8%`, `30.4%`, `9.0%` 높았지만 C=10·20·50·100에서는 `0.8~9.8%` 낮았다.
- 따라서 **이번에 실측한 세 설정 안에서는** 지속적인 C≥10의 보수적 기본값은 `baseline-cpu8`, C≤5 interactive 부하의 후보는 `mtp-cpu8`이다. 정의된 traffic mix가 없어 혼합 부하 최적값은 주장하지 않는다. `mtp-kv-tuned-cpu8`은 범용 기본값으로 채택하지 않으며, 이는 전체 CPU 최적화 공간의 최적값을 증명한 결과가 아니다.

7개 phase 시간을 단순 합산하면 baseline-cpu8은 `3,840.71초`, MTP는 `3,576.55초`, 결합 설정은 `3,441.59초`다. 동일한 총 44,800 output tokens 기준 합산 처리량은 각각 `11.66`, `12.53`, `13.02 token/s`다. 결합 설정의 합산값은 C=1·2의 큰 실행 간 차이에 강하게 영향을 받으므로 고동시성 capacity가 좋아졌다는 뜻이 아니다. 운영 설정은 목표 동시성별 결과로 선택해야 한다.

자동 검증표와 그래프는 [comparison-cpu8-optimizations/REPORT.md](../benchmark/results/comparison-cpu8-optimizations/REPORT.md), 재분석용 원표는 [comparison.csv](../benchmark/results/comparison-cpu8-optimizations/comparison.csv)에 있다.

## 장비·모델·런타임 선택 근거

| 항목 | 값 |
|---|---|
| Host | Apple M4, logical CPU 10, RAM 16GiB |
| Docker Desktop VM | Linux/ARM64, 10 vCPU, 약 7.65GiB |
| Kubernetes | Kind control-plane 1 + worker 1 |
| Runtime | vLLM `0.26.0+cpu`, `device_config=cpu` |
| Model | `Qwen/Qwen3.5-0.8B`, BF16, max context 2,048 |
| Image | `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0` |
| Pod resources | CPU request/limit `4/8`, memory request/limit `4Gi/6656Mi` |

Qwen3.5-0.8B는 제한된 Docker VM 메모리에 BF16 weight, runtime, KV cache를 함께 수용할 수 있고 checkpoint에 native MTP layer가 있다. 따라서 모델과 weight를 바꾸지 않고 speculative decoding 설정만 비교할 수 있다. 세 설정은 같은 image와 model revision을 사용했으므로 품질 또는 checkpoint 차이가 서빙 성능 변화에 섞이지 않는다.

GPU를 사용하지 않았다는 사실은 Kubernetes에 GPU resource가 없다는 것뿐 아니라 vLLM 시작 로그의 `device_config=cpu`와 cgroup `cpu.max=800000 100000`으로 확인했다.

## 실험 설계와 변경점

| 설정 | CPU | MTP | KV / max sequences | 기동 시 KV capacity |
|---|---:|---|---|---:|
| `baseline-cpu8` | 8 | off | 512MiB / 20 | 19,894 tokens |
| `mtp-cpu8` | 8 | `qwen3_next_mtp`, 2 tokens | 512MiB / 20 | 9,137 tokens |
| `mtp-kv-tuned-cpu8` (legacy ID) | 8 | 위와 동일 | 768MiB / 24 | 13,705 tokens |

첫 번째 최적화는 Qwen 모델 전용 native MTP다.

```text
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

두 번째 실험은 BF16 KV dtype을 유지한 capacity bundle이다.

```diff
- --kv-cache-memory-bytes 536870912
- --max-num-seqs 20
+ --kv-cache-memory-bytes 805306368
+ --max-num-seqs 24
```

`baseline-cpu8 → mtp-cpu8`은 MTP만 추가했으므로 MTP 단독 A/B다. 반면 `mtp-cpu8 → mtp-kv-tuned-cpu8`은 KV byte budget과 `max-num-seqs` 두 값을 함께 바꿨으므로 **KV 단독 A/B가 아니다**. 이 세 설정만으로는 capacity bundle을 분해할 수 없었다. 후속 2×2 결과에서는 KV-only가 running 5→8을 만들었지만 C=10·20 throughput을 각각 10.2%·10.4% 낮췄고, maxseq-only는 running/waiting을 바꾸지 않았다. `mtp-kv-tuned-cpu8`이라는 이름은 결과 경로 호환성을 위한 legacy artifact ID다.

실측 peak running은 MTP에서 최대 5, bundle에서 최대 8로 두 설정 모두 기존 `max-num-seqs=20`보다 낮았다. 따라서 이 역사적 세 설정만 보면 20이라는 상한이 직접 포화된 흔적은 없고 KV capacity 증가가 running 폭 변화의 유력 원인이었다. 당시 남아 있던 혼합 변수는 후속 `KV768MiB / max-num-seqs20`과 `KV512MiB / max-num-seqs24` 셀을 추가한 [2×2 분리 실험](../optimization/cpu8-factorial/README.md)에서 해소했다. 그 결과 maxseq-only는 scheduler 상태를 바꾸지 않았고, KV-only가 running을 5에서 8로 늘린 사실을 확인했다.

각 동시성 단계는 같은 100건 중 최대 C건만 동시에 in-flight가 되는 closed-loop 방식이다. 요청당 output은 정확히 64 tokens이며 `temperature=0`, `ignore_eos=true`, Automatic Prefix Caching off다. 단계별 warmup 3건은 통계에서 제외했다.

## 데이터 유효성

- 세 설정의 정식 요청 `2,100/2,100`건 성공, 실패 0건
- 각 phase에서 client prompt `29,791`, completion `6,400` tokens와 server counter 증가량 일치
- 동일 prompt 파일 SHA-256와 동일 순서·benchmark config 확인
- 정식 phase의 UTC wall clock과 monotonic timer 허용 오차 통과
- metric scrape error, OOM kill, Pod restart 모두 0
- MTP·결합 설정의 prefix cache query/hit 0, preemption 0
- 비교기가 rendered container spec을 검사해 의도한 단계 변경 이외의 차이가 없음을 확인

CPU8 baseline C=5는 사용자 요청으로 유효한 두 번째 표본을 공식값으로 사용했다. 첫 유효 표본과 재측정 output throughput 차이는 19.5%였다. 따라서 이번 MTP·capacity bundle 비교도 단일 반복의 host background load와 thermal 변동을 포함하며, 특히 낮은 동시성의 작은 차이를 확정값으로 해석하지 않는다. 최초 표본은 [baseline-cpu8/excluded](../benchmark/results/baseline-cpu8/excluded/)에 보존돼 있다.

## 지표를 선택한 이유

| 관점 | 지표 | 판단 목적 |
|---|---|---|
| 정확성·안전성 | success, client/server token counter, OOM/restart | 빠르더라도 실패·누락·재시작이 있으면 개선으로 보지 않음 |
| 사용자 체감 | E2E p50/p95/p99 | queue를 포함한 요청 전체 지연 |
| Prefill/queue | TTFT p50/p95/p99 | 입력 처리와 scheduler waiting 영향 분리 |
| Decode | TPOT p50/p95/p99 | 첫 token 이후 생성 간격과 active batch 경쟁 확인 |
| Capacity | request/s, prompt/output token/s | 일정 시간에 실제 완료한 작업량 |
| Scheduler/KV | running, waiting, KV usage, preemption | 실행 폭과 queue/cache 병목 연결 |
| MTP | drafted/accepted tokens, acceptance | speculative verification의 유효 제안 비율 확인 |
| 자원 | Pod cgroup CPU/RAM | CPU 포화와 memory headroom 확인 |

평균은 tail latency를 숨길 수 있어 p95를 중심으로 보되, 고정 100건 phase의 최종 처리량도 함께 판단했다. E2E·TTFT·TPOT p95는 서로 다른 요청이 percentile 위치를 차지할 수 있으므로 서로 더하지 않는다.

## Before/after 실측

처리량 단위는 output token/s다. `bundle`은 `MTP2 + KV768MiB + max-num-seqs24`를 뜻한다.

| C | Baseline | MTP2 | Bundle | MTP vs base | Bundle vs MTP | Bundle vs base |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.44 | 8.24 | 9.33 | +27.8% | +13.3% | +44.8% |
| 2 | 9.28 | 10.30 | 12.10 | +11.0% | +17.4% | +30.4% |
| 5 | 13.16¹ | 14.38 | 14.35 | +9.3% | -0.3% | +9.0% |
| 10 | 14.94 | 14.41 | 14.83 | -3.5% | +2.9% | -0.8% |
| 20 | 16.22 | 14.62 | 14.75 | -9.9% | +0.9% | -9.0% |
| 50 | 15.03 | 14.89 | 14.33 | -0.9% | -3.7% | -4.6% |
| 100 | 15.15 | 15.18 | 13.66 | +0.2% | -10.0% | -9.8% |

지연과 scheduler pressure는 별도로 본다. 각 셀의 순서는 `baseline / MTP2 / bundle`이다.

| C | E2E p95 (s) | Peak running | Peak waiting | MTP / bundle acceptance |
|---:|---:|---:|---:|---:|
| 1 | 15.61 / 13.35 / 12.28 | 1 / 1 / 1 | 0 / 0 / 0 | 76.7% / 76.7% |
| 2 | 18.54 / 18.42 / 15.94 | 2 / 2 / 2 | 0 / 0 / 0 | 76.2% / 76.3% |
| 5 | 34.32 / 30.22 / 30.35 | 5 / 5 / 5 | 0 / 0 / 0 | 75.2% / 76.1% |
| 10 | 53.92 / 52.75 / 55.39 | 10 / 5 / 8 | 1 / 5 / 2 | 75.6% / 75.6% |
| 20 | 109.94 / 93.47 / 100.32 | 16 / 5 / 8 | 9 / 15 / 12 | 75.8% / 76.0% |
| 50 | 230.02 / 219.23 / 228.51 | 16 / 5 / 8 | 41 / 45 / 42 | 76.7% / 75.8% |
| 100 | 415.57 / 415.08 / 463.65 | 16 / 5 / 8 | 91 / 95 / 92 | 76.5% / 76.5% |

Peak running과 peak waiting은 각각의 metric 시계열에서 독립적으로 구한 최댓값이며 같은 시점의 한 쌍이 아니다. 예를 들어 `16 / 91`을 동시에 107건이 있었다는 뜻으로 읽으면 안 된다.

¹ C=5 baseline은 사용자 요청에 따라 두 번째 유효 표본을 공식값으로 채택했다. 첫 유효 표본과 output throughput 차이는 19.5%였으므로 단일 실행의 분산을 함께 고려해야 한다.

## 왜 개선되거나 악화됐는가

### C=1~5: MTP의 decode 이득

MTP의 speculative acceptance는 모든 phase에서 약 `75~77%`였다. active sequence가 적을 때는 다음 두 token 후보 중 상당수를 target verification 한 번에 수용하는 이득이 draft/verification 비용보다 컸다. MTP 단독의 C=1·2·5 throughput이 baseline보다 개선된 이유다.

Bundle은 MTP 단독보다 C=1·2에서 13.3%, 17.4% 높았지만 이 구간의 peak running은 1·2, KV 사용률은 최대 24.4%에 불과하다. KV 용량이나 `max-num-seqs`가 병목이 아닌 구간이므로 이 차이를 capacity bundle의 인과 효과로 볼 수 없다. 새 Pod/JIT 상태, host background load, thermal 변동이 포함된 실행 간 차이로 보는 것이 안전하다. C=5에서는 두 MTP 설정이 0.3% 차이로 사실상 같다는 결과가 이 해석을 뒷받침한다.

### C=10~20: queue 감소와 CPU 경쟁의 교차

512MiB MTP는 같은 용량의 baseline보다 KV token capacity가 `19,894→9,137`로 줄어 C=10부터 peak running 5, waiting 5를 기록했다. Capacity bundle 적용 후 기동 시 KV capacity는 13,705 tokens가 되고 running은 8, waiting은 2로 바뀌었다. 이때 KV와 `max-num-seqs`를 함께 바꿨지만 running 8은 옛 상한 20보다 작으므로, 실행 폭 증가는 KV budget의 영향일 가능성이 크다. Bundle의 C=10 TTFT p95는 MTP 단독의 `31.30→20.55초`로 좋아졌다.

그러나 실행 요청 8개가 같은 8-core quota와 memory bandwidth를 나누고 MTP draft/verification도 수행한다. C=10 TPOT p95는 MTP 단독 `414.52→623.58ms`, C=20은 `386.05→644.01ms`로 악화됐다. C=20 output throughput은 bundle 적용 후에도 MTP 대비 0.9%만 늘었고 baseline보다 9.0% 낮았다. queue 일부를 running으로 옮겼지만 총 compute capacity는 늘지 않은 결과다.

### C=50~100: capacity bundle의 더 큰 active batch가 역효과

Bundle은 MTP 단독보다 running을 3개 늘리고 waiting을 3개 줄였지만 C=50·100 TPOT p95를 각각 `374.28→644.35ms`, `405.88→723.46ms`로 악화시켰다. C=100에서는 output throughput이 MTP보다 10.0% 줄고 E2E p95가 `415.08→463.65초`로 11.7% 늘었다.

MTP 단독의 고동시성 TPOT가 baseline보다 낮아도 총 throughput이 반드시 높지는 않다. MTP는 동시에 5개만 decode해 active request 하나당 token 간격은 짧지만, 더 많은 요청이 first token 전에 queue에서 기다린다. 반대로 bundle은 더 많은 요청을 실행해 queue를 줄이지만 active request끼리 CPU를 경쟁시킨다. 이 로컬 장비에서는 C=50 이상에서 후자의 비용이 더 컸다.

MTP 단독의 phase 평균 CPU 평균은 `7.71 cores`, 결합은 `7.61 cores`로 8-core quota에 가깝고 baseline-cpu8의 `7.11 cores`보다 높다. acceptance는 두 MTP 설정 모두 전체 약 76.1%로 동일하다. 따라서 고동시성 악화의 원인은 acceptance 하락이 아니라 speculative work와 더 큰 active batch의 CPU/cache/memory-bandwidth 경쟁으로 해석할 수 있다.

## 자원과 안정성

| 지표 | baseline-cpu8 | mtp-cpu8 | bundle (legacy `mtp-kv-tuned-cpu8`) | 해석 |
|---|---:|---:|---:|---|
| phase 평균 CPU의 평균 | 7.11 | 7.71 | 7.61 cores | MTP 계열은 CPU quota에 더 가까움 |
| 최대 Pod RAM | 6.15 | 6.10 | 6.34GiB | 결합 설정의 limit 여유는 약 0.16GiB |
| 총 preemption | 2 | 0 | 0 | MTP 두 설정은 선점 없이 완주 |
| OOM kill / restart | 0 / 0 | 0 / 0 | 0 / 0 | 세 설정 모두 기능적으로 안정적 |

768MiB KV는 6.5GiB limit 안에서 완주했지만 약 0.16GiB의 headroom은 운영 환경에 충분하지 않다. 긴 context, library allocator 변동, probe와 sidecar가 추가되면 OOM 위험이 있다. preemption 제거와 waiting 감소는 긍정적이지만 고동시성 처리량 손실을 상쇄하지 못했다.

## 효과가 없거나 실패한 최적화

### FP8 KV cache: Apple M4/ARM64에서 기동 실패

처음 후보였던 `--kv-cache-dtype fp8 --calculate-kv-scales`를 별도 overlay로 실제 배포했지만 server 초기화 중 다음 예외가 발생했다.

```text
NotImplementedError: FP8 KV cache on CPU requires x86 with AVX-512 or AMX.
```

vLLM 공통 CLI가 `fp8`을 파싱하는 것과 Apple ARM64 CPU용 실행 kernel이 존재하는 것은 다르다. 실패 요청을 부하 결과에 섞지 않고 startup log, 이벤트, 복구 절차를 [FP8 KV 실패 리포트](03_FAILED_OPTIMIZATION_FP8_KV.md)에 별도로 보존했다. 이번 두 번째 정식 최적화는 FP8이 아니라 BF16 KV capacity 조정이다.

### KV 768MiB + max sequences 24 bundle: queue에는 효과, 범용 성능에는 역효과

실행 폭 `5→8`과 waiting `-3`은 의도대로 나타났다. 하지만 C=5에서는 MTP 대비 throughput 차이가 -0.3%, C=10·20은 +2.9%·+0.9%에 그쳤고 C=50·100은 -3.7%·-10.0%였다. “running을 늘리면 throughput도 오른다”는 가설이 CPU 포화 환경에서는 성립하지 않았다. 이 결과는 KV-only 또는 `max-num-seqs`-only 효과가 아니라 두 값을 함께 바꾼 bundle 효과다.

### Generic MTP 5 tokens: 기존 pilot에서 후보 탈락

모델에 MTP layer가 1개뿐인데 5 tokens를 제안하면 layer를 반복 사용한다. 기존 CPU6 pilot에서 acceptance가 약 48%로 MTP2보다 낮고 C=20 throughput도 9.01 token/s에 그쳐 정식 CPU8 재측정 후보에서 제외했다. 이번 실험은 모델 전용 MTP2만 사용해 불필요한 700건 재실행을 피했다.

## 로컬 K8s에서 GPU production으로 가져갈 것

### 그대로 유효한 것

- model/runtime/image/workload hash를 고정하고 before/after를 같은 요청으로 비교하는 방식
- baseline을 보존하고 Kustomize overlay로 한 단계씩 변경하는 실험 구조
- client/server token counter와 wall/monotonic timer를 교차 검증하는 데이터 품질 기준
- E2E·TTFT·TPOT·throughput과 running/waiting/KV/resource를 함께 보는 분석 원칙
- readiness/liveness, Service, worker scheduling, 실패 기록과 rollback 절차

### 다시 설계할 것

| 영역 | 로컬 CPU 구성 | GPU production 재설계 |
|---|---|---|
| Runtime | ARM64 CPU vLLM | CUDA/ROCm, driver, vLLM, GPU generation별 kernel compatibility 검증 |
| Scheduling | worker 1개, CPU nodeSelector | GPU device plugin/operator, taint/toleration, topology, MIG와 anti-affinity |
| Parallelism | replica 1, process 1 | tensor/pipeline/data parallel, NVLink/NCCL topology와 replica sizing |
| Availability | Recreate, 단일 worker | RollingUpdate, 다중 replica/AZ, PDB, drain·node failure 검증 |
| Autoscaling | 없음 | CPU HPA보다 waiting, queue depth, TTFT, KV pressure 기반 custom metric scaling |
| Model 배포 | weight를 image에 포함 | object storage/registry, local NVMe cache, prefetch와 image/weight lifecycle 분리 |
| Observability | 실행 중 CSV 수집 | Prometheus/Grafana, 중앙 로그·trace, SLO와 alert, 장기 capacity trend |
| Quantization | BF16, FP8 startup 실패 | 목표 GPU에서 FP8/INT8 kernel, scale calibration, 품질 회귀까지 검증 |

현재 Docker VM 7.65GiB에서는 6.34GiB Pod를 두 개 띄우기 어려워 HPA scale-out 결과가 OOM/Pending으로 왜곡된다. worker도 하나이므로 node 중단 후 다른 worker로 재스케줄할 대상이 없다. 선택 과제를 의미 있게 수행하려면 Docker memory를 늘리고 worker를 최소 두 개로 재구성해야 한다.

## 다음 최적화 우선순위

현재 Pod는 8-core quota인데 vLLM auto binding은 inference OpenMP thread 9개와 reserved core 1개를 구성했다. 따라서 같은 모델·정밀도를 유지한 다음 단일 변수 A/B는 CPU thread/affinity가 가장 우선이다. vLLM CPU 가이드도 online serving에서 frontend용 1~2 CPU를 남기고 thread binding을 먼저 조정하라고 권장한다.

1. `auto(9 threads)`, explicit 8 threads, explicit 7 threads를 각각 같은 700건으로 비교하고 `cpu.stat`의 throttling delta를 함께 기록한다.
2. MTP `num_speculative_tokens=1`과 현재 2를 비교한다. Qwen3.5 공식 recipe는 저동시성 latency 목적에 MTP1을 제안하고, 고동시성에서는 speculative token이 KV capacity를 사용해 throughput을 낮출 수 있다고 설명한다.
3. MTP2를 고정한 2×2 `KV 512/768MiB × max-num-seqs 20/24`로 이번 confound를 제거한다. 이후 `max-num-seqs`와 `max-num-batched-tokens`를 한 번에 하나씩 sweep해 throughput/TTFT Pareto를 찾는다.
4. 세 설정을 교차 순서로 최소 3회 반복하고 중앙값, IQR 또는 bootstrap 신뢰구간을 제시한다. 특히 capacity가 병목이 아닌 C=1·2의 실행 간 차이를 분리해야 한다.
5. Automatic Prefix Caching은 이번 cold/distinct-prefix workload에서는 계속 끄고, 공통 system prompt나 multi-turn 대화가 있는 별도 cold/warm 실험에서만 평가한다.
6. weight INT8/INT4는 Apple Docker VM에서 실제 kernel 지원과 정확도 회귀를 먼저 검증한 뒤 독립 실험한다. GPU 환경에서는 chunked prefill, prefix-aware routing, tensor parallel, disaggregated prefill/decode를 실제 prompt 길이와 SLO에 맞춰 검증한다.

상세 실험 행렬과 인과성 표시는 [최적화 실험 행렬](../optimization/EXPERIMENT_MATRIX.md)에 정리한다.

공식 근거: [vLLM CPU 설치·튜닝 가이드](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/index.html), [vLLM Qwen3.5 recipe](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)

## 재현 명령과 산출물

```bash
make deploy-baseline-cpu8
make benchmark-baseline-cpu8

make deploy-mtp-cpu8
make smoke
make benchmark-mtp-cpu8

make deploy-mtp-kv-tuned-cpu8
make smoke
make benchmark-mtp-kv-tuned-cpu8

make benchmark-compare-cpu8-optimizations
```

- Baseline CPU8: [benchmark/results/baseline-cpu8](../benchmark/results/baseline-cpu8/)
- MTP CPU8: [benchmark/results/mtp-cpu8](../benchmark/results/mtp-cpu8/)
- Capacity bundle CPU8 (legacy ID): [benchmark/results/mtp-kv-tuned-cpu8](../benchmark/results/mtp-kv-tuned-cpu8/)
- 자동 비교 CSV·그래프: [benchmark/results/comparison-cpu8-optimizations](../benchmark/results/comparison-cpu8-optimizations/)
- 실험 절차: [optimization/cpu8-mtp-kv/README.md](../optimization/cpu8-mtp-kv/README.md)
- FP8 실패 상세: [reports/03_FAILED_OPTIMIZATION_FP8_KV.md](03_FAILED_OPTIMIZATION_FP8_KV.md)
