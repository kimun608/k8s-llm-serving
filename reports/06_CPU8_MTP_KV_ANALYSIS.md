# CPU limit 8 고정: MTP와 KV capacity 최적화 분석

## 결론

CPU limit을 `8`로 고정한 상태에서 `baseline-cpu8`, `mtp-cpu8`, `mtp-kv-tuned-cpu8`을 동일한 100개 prompt와 동시성 `1, 2, 5, 10, 20, 50, 100`으로 비교했다. 설정별 700건, 총 2,100건이 모두 성공했고 client/server token counter, wall clock, metric scrape, OOM을 자동 검증했다.

결과는 부하 영역에 따라 갈렸다.

- MTP 단독은 C=1·2·5 output throughput을 baseline-cpu8보다 각각 `27.8%`, `11.0%`, `9.3%` 높였다.
- MTP 단독은 C=10·20에서 각각 `3.5%`, `9.9%` 낮았고, C=50·100은 `-0.9%`, `+0.2%`로 사실상 동률이었다.
- KV를 `512→768MiB`, max sequences를 `20→24`로 늘리면 MTP 환경의 peak running은 고동시성에서 `5→8`, peak waiting은 3개 줄었다. 그러나 C=50·100 output throughput은 MTP 단독보다 각각 `3.7%`, `10.0%` 낮아졌다.
- 결합 설정은 baseline-cpu8 대비 C=1·2·5에서 `44.8%`, `30.4%`, `9.0%` 높았지만 C=10·20·50·100에서는 `0.8~9.8%` 낮았다.
- 따라서 지속적인 C≥10 또는 혼합 부하의 기본값은 `baseline-cpu8`, C≤5 interactive 부하의 후보는 `mtp-cpu8`이 적절하다. `mtp-kv-tuned-cpu8`은 범용 기본값으로 채택하지 않는다.

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
| `mtp-kv-tuned-cpu8` | 8 | 위와 동일 | 768MiB / 24 | 13,705 tokens |

첫 번째 최적화는 Qwen 모델 전용 native MTP다.

```text
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

두 번째 최적화는 BF16 KV dtype을 유지한 capacity/scheduler 조정이다.

```diff
- --kv-cache-memory-bytes 536870912
- --max-num-seqs 20
+ --kv-cache-memory-bytes 805306368
+ --max-num-seqs 24
```

`baseline-cpu8 → mtp-cpu8`은 MTP 단독 효과, `mtp-cpu8 → mtp-kv-tuned-cpu8`은 KV/scheduler 증분 효과, `baseline-cpu8 → mtp-kv-tuned-cpu8`은 결합 효과로 분리했다. 그 밖의 image, model, CPU·memory, context, batched tokens, workload와 API parameter는 고정했다.

각 동시성 단계는 같은 100건 중 최대 C건만 동시에 in-flight가 되는 closed-loop 방식이다. 요청당 output은 정확히 64 tokens이며 `temperature=0`, `ignore_eos=true`, Automatic Prefix Caching off다. 단계별 warmup 3건은 통계에서 제외했다.

## 데이터 유효성

- 세 설정의 정식 요청 `2,100/2,100`건 성공, 실패 0건
- 각 phase에서 client prompt `29,791`, completion `6,400` tokens와 server counter 증가량 일치
- 동일 prompt 파일 SHA-256와 동일 순서·benchmark config 확인
- 정식 phase의 UTC wall clock과 monotonic timer 허용 오차 통과
- metric scrape error, OOM kill, Pod restart 모두 0
- MTP·결합 설정의 prefix cache query/hit 0, preemption 0
- 비교기가 rendered container spec을 검사해 의도한 단계 변경 이외의 차이가 없음을 확인

CPU8 baseline C=5는 사용자 요청으로 유효한 두 번째 표본을 공식값으로 사용했다. 첫 유효 표본과 재측정 output throughput 차이는 19.5%였다. 따라서 이번 MTP·KV 비교도 단일 반복의 host background load와 thermal 변동을 포함하며, 특히 낮은 동시성의 작은 차이를 확정값으로 해석하지 않는다. 최초 표본은 [baseline-cpu8/excluded](../benchmark/results/baseline-cpu8/excluded/)에 보존돼 있다.

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

| C | Output tok/s base / MTP / MTP+KV | MTP vs base | KV vs MTP | Combined vs base | E2E p95 base → combined | Peak run/wait base / MTP / combined |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.44 / 8.24 / 9.33 | +27.8% | +13.3% | +44.8% | 15.61s → 12.28s | 1/0 / 1/0 / 1/0 |
| 2 | 9.28 / 10.30 / 12.10 | +11.0% | +17.4% | +30.4% | 18.54s → 15.94s | 2/0 / 2/0 / 2/0 |
| 5 | 13.16 / 14.38 / 14.35 | +9.3% | -0.3% | +9.0% | 34.32s → 30.35s | 5/0 / 5/0 / 5/0 |
| 10 | 14.94 / 14.41 / 14.83 | -3.5% | +2.9% | -0.8% | 53.92s → 55.39s | 10/1 / 5/5 / 8/2 |
| 20 | 16.22 / 14.62 / 14.75 | -9.9% | +0.9% | -9.0% | 109.94s → 100.32s | 16/9 / 5/15 / 8/12 |
| 50 | 15.03 / 14.89 / 14.33 | -0.9% | -3.7% | -4.6% | 230.02s → 228.51s | 16/41 / 5/45 / 8/42 |
| 100 | 15.15 / 15.18 / 13.66 | +0.2% | -10.0% | -9.8% | 415.57s → 463.65s | 16/91 / 5/95 / 8/92 |

## 왜 개선되거나 악화됐는가

### C=1~5: MTP의 decode 이득

MTP의 speculative acceptance는 모든 phase에서 약 `75~77%`였다. active sequence가 적을 때는 다음 두 token 후보 중 상당수를 target verification 한 번에 수용하는 이득이 draft/verification 비용보다 컸다. MTP 단독의 C=1·2·5 throughput이 baseline보다 개선된 이유다.

결합 설정은 MTP 단독보다 C=1·2에서 13.3%, 17.4% 높았지만 이 구간의 peak running은 1·2, KV 사용률은 최대 24.4%에 불과하다. 추가 KV 용량이 사용되지 않는 조건이므로 이 차이를 KV 최적화의 인과 효과로 볼 수 없다. 새 Pod/JIT 상태, host background load, thermal 변동이 포함된 실행 간 차이로 보는 것이 안전하다. C=5에서는 두 MTP 설정이 0.3% 차이로 사실상 같다는 결과가 이 해석을 뒷받침한다.

### C=10~20: queue 감소와 CPU 경쟁의 교차

512MiB MTP는 같은 용량의 baseline보다 KV token capacity가 `19,894→9,137`로 줄어 C=10부터 peak running 5, waiting 5를 기록했다. KV를 768MiB로 늘리면 capacity가 13,705 tokens가 되고 running은 8, waiting은 2로 바뀌었다. 결합 설정 C=10 TTFT p95는 MTP 단독의 `31.30→20.55초`로 좋아졌다.

그러나 실행 요청 8개가 같은 8-core quota와 memory bandwidth를 나누고 MTP draft/verification도 수행한다. C=10 TPOT p95는 MTP 단독 `414.52→623.58ms`, C=20은 `386.05→644.01ms`로 악화됐다. C=20 output throughput은 KV 증설 후에도 MTP 대비 0.9%만 늘었고 baseline보다 9.0% 낮았다. queue 일부를 running으로 옮겼지만 총 compute capacity는 늘지 않은 결과다.

### C=50~100: 더 큰 active batch가 역효과

KV 확대는 MTP 단독보다 running을 3개 늘리고 waiting을 3개 줄였지만 C=50·100 TPOT p95를 각각 `374.28→644.35ms`, `405.88→723.46ms`로 악화시켰다. C=100에서는 output throughput이 MTP보다 10.0% 줄고 E2E p95가 `415.08→463.65초`로 11.7% 늘었다.

MTP 단독의 고동시성 TPOT가 baseline보다 낮아도 총 throughput이 반드시 높지는 않다. MTP는 동시에 5개만 decode해 active request 하나당 token 간격은 짧지만, 더 많은 요청이 first token 전에 queue에서 기다린다. 반대로 KV 확대는 더 많은 요청을 실행해 queue를 줄이지만 active request끼리 CPU를 경쟁시킨다. 이 로컬 장비에서는 C=50 이상에서 후자의 비용이 더 컸다.

MTP 단독의 phase 평균 CPU 평균은 `7.71 cores`, 결합은 `7.61 cores`로 8-core quota에 가깝고 baseline-cpu8의 `7.11 cores`보다 높다. acceptance는 두 MTP 설정 모두 전체 약 76.1%로 동일하다. 따라서 고동시성 악화의 원인은 acceptance 하락이 아니라 speculative work와 더 큰 active batch의 CPU/cache/memory-bandwidth 경쟁으로 해석할 수 있다.

## 자원과 안정성

| 지표 | baseline-cpu8 | mtp-cpu8 | mtp-kv-tuned-cpu8 | 해석 |
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

### KV 768MiB / 24 sequences: queue에는 효과, 범용 성능에는 역효과

실행 폭 `5→8`과 waiting `-3`은 의도대로 나타났다. 하지만 C=5에서는 MTP 대비 throughput 차이가 -0.3%, C=10·20은 +2.9%·+0.9%에 그쳤고 C=50·100은 -3.7%·-10.0%였다. “running을 늘리면 throughput도 오른다”는 가설이 CPU 포화 환경에서는 성립하지 않았다.

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

## 시간이 더 있다면

1. 세 설정을 교차 순서로 최소 3회 반복하고 중앙값, IQR 또는 bootstrap 신뢰구간을 제시한다. 특히 KV가 사용되지 않는 C=1·2의 실행 간 차이를 분리해야 한다.
2. MTP/non-MTP replica를 분리하고 queue depth 또는 요청 SLO에 따라 C≤5 요청만 MTP로 라우팅한다.
3. MTP tokens `1`과 `2`, KV bytes, max sequences, max batched tokens를 작은 grid로 탐색하되 throughput과 TTFT p95의 다목적 함수로 선택한다.
4. OpenMP thread 수를 8-core quota에 맞추고 affinity/NUMA 정책을 독립 A/B해 CPU throttling과 memory bandwidth 영향을 줄인다.
5. 지원 x86 CPU에서는 oneDNN/IPEX와 weight INT8/INT4를 비교하고 task 정확도·perplexity 회귀도 함께 측정한다.
6. GPU 환경에서는 chunked prefill, prefix-aware routing, tensor parallel, disaggregated prefill/decode를 실제 prompt 길이와 SLO에 맞춰 검증한다.

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
- MTP+KV CPU8: [benchmark/results/mtp-kv-tuned-cpu8](../benchmark/results/mtp-kv-tuned-cpu8/)
- 자동 비교 CSV·그래프: [benchmark/results/comparison-cpu8-optimizations](../benchmark/results/comparison-cpu8-optimizations/)
- 실험 절차: [optimization/cpu8-mtp-kv/README.md](../optimization/cpu8-mtp-kv/README.md)
- FP8 실패 상세: [reports/03_FAILED_OPTIMIZATION_FP8_KV.md](03_FAILED_OPTIMIZATION_FP8_KV.md)
