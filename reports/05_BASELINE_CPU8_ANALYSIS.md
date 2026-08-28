# Baseline 단일 변경 분석: CPU limit 6 → 8

> 이 문서는 CPU quota 단일 변경 A/B다. MTP와 KV/max-seqs 분리 실험을 포함한 최종 결론은 [최종 종합 분석](07_FINAL_COMPREHENSIVE_ANALYSIS.md)을 따른다.

## 결론

현재 Apple M4 로컬 환경에서 baseline의 Kubernetes container CPU limit만 `6`에서 `8`로 올리는 변경은 채택할 가치가 있다. 동일한 100개 prompt를 동시성 `1, 2, 5, 10, 20, 50, 100`에서 각각 실행한 최신 결과에서 output throughput은 7개 구간 모두 `+11.7~24.8%` 개선됐다. 고정 출력 44,800 tokens의 phase 시간 합은 `4,598.07초 → 3,840.71초`로 16.5% 줄었고 합산 output throughput은 `9.74 → 11.66 token/s`, 즉 19.7% 증가했다.

최초 CPU 8 C=5는 baseline보다 throughput이 2.3% 낮았지만 사용자 요청에 따른 두 번째 실행에서는 16.7% 높았다. 두 CPU 8 실행의 throughput 차이가 19.5%이므로 최신 결과가 좋아졌다는 사실과 별개로 C=5 개선 폭의 반복 안정성은 아직 입증되지 않았다. 이번 워크로드와 장비에서 측정된 가장 단순하고 효과적인 한 필드 변경이라는 결론이며, production sizing 전에는 3회 이상 반복 측정이 필요하다.

자동 검증표와 그래프는 [comparison-cpu8/REPORT.md](../benchmark/results/comparison-cpu8/REPORT.md), 재분석용 CSV는 [comparison.csv](../benchmark/results/comparison-cpu8/comparison.csv)에 있다.

## 실험 질문과 유일한 변경

가설은 10-vCPU Docker Desktop VM에서 vLLM Pod의 6-core CFS quota가 CPU 추론을 제한하므로, cluster overhead를 위한 2 vCPU를 남긴 8-core quota가 처리량을 높인다는 것이다.

```diff
 resources:
   limits:
-    cpu: "6"
+    cpu: "8"
```

비교기는 두 실행의 container 명세를 구조적으로 대조했다. CPU limit 외 image, args, env, CPU request, memory, model, MTP, KV cache, scheduler 설정이 같지 않으면 결과 생성을 중단한다. benchmark config는 `experiment` 이름을 제외하고 동일하고 prompt 파일 SHA-256도 일치한다.

## 장비와 고정 조건

| 항목 | 값 |
|---|---|
| Host | Apple M4, logical CPU 10, RAM 16GiB |
| Docker Desktop VM | Linux/ARM64, 10 vCPU, 7.65GiB |
| Kubernetes | Kind control-plane 1 + worker 1; 두 node container가 같은 Docker VM 자원을 공유 |
| Runtime | vLLM `0.26.0+cpu`, `device_config=cpu` |
| Model | `Qwen/Qwen3.5-0.8B`, BF16, max context 2,048 |
| Speculative decoding | off, `speculative_config=None` |
| KV/APC | 512MiB KV, Automatic Prefix Caching off |
| Scheduler | `max-num-seqs=20`, `max-num-batched-tokens=2048` |
| Pod resources | request CPU 4/memory 4Gi; limit memory 6.5Gi; CPU limit만 6 또는 8 |
| Workload | 공개 benchmark 4종 × 25개, 고정 prompt 100개 |
| 요청 | C별 100건, streaming, 64 output tokens, `ignore_eos=true`, temperature 0 |
| 동시성 | `1, 2, 5, 10, 20, 50, 100`; 설정별 총 700건 |

CPU-only 조건은 Kubernetes resource 설정에 GPU가 없다는 사실뿐 아니라 vLLM startup log의 `device_config=cpu`와 Pod cgroup의 `cpu.max`로 확인했다. CPU 8 배포의 실제 값은 `800000 100000`, 즉 100ms period마다 최대 800ms CPU time이다. vLLM은 core id 0~8의 OpenMP thread 9개를 사용하므로 8-core quota에서도 thread 수보다 quota가 하나 작다.

## 데이터 유효성

- 정식 비교 요청 1,400건은 모두 성공했다.
- 각 phase의 client prompt/completion token 합과 vLLM server counter 증가량이 일치했다.
- prefix cache hit는 0으로 유지됐고 OOM kill과 Pod restart도 0이었다.
- 정식 14개 phase의 UTC wall clock과 monotonic timer 차이는 모두 0.05초 이하였다.
- metric scrape error는 모든 정식 phase에서 0이었다.

장시간 실행 중 host 중단이 있었던 초기 표본 두 개는 결과에서 제외했다. CPU 6 C=2 표본은 wall clock과 timer 차이가 5,365.15초, CPU 8 C=10 표본은 8,169.92초였다. 원본 request, metric, phase metadata와 제외 사유를 각각 [baseline/excluded](../benchmark/results/baseline/excluded/)와 [baseline-cpu8/excluded](../benchmark/results/baseline-cpu8/excluded/)에 보존하고 같은 Pod 설정·100 prompt로 재측정했다.

최초 CPU 8 C=5는 wall clock과 metric 측면에서 유효한 표본이므로 중단 표본으로 취급하지 않는다. 사용자 요청으로 확인 실행을 수행하면서 원본을 같은 `baseline-cpu8/excluded/` 아래에 보존했고, 자동 비교의 정식 C=5 값만 최신 실행으로 교체했다. 재측정 기능은 `--resume --rerun-concurrencies`로 재현할 수 있으며 어떤 이유로 교체하더라도 기존 표본을 덮어쓰기 전에 자동 보존한다.

## Before/after 결과

처리량은 증가가 좋고 latency는 감소가 좋다.

| C | Output tok/s 6 → 8 | 변화 | E2E p95 변화 | TTFT p95 변화 | TPOT p95 변화 | Avg CPU 6 → 8 | Peak run/wait 6 → 8 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5.16 → 6.44 | +24.8% | -17.8% | -16.2% | -20.6% | 5.99 → 7.78 | 1/0 → 1/0 |
| 2 | 7.64 → 9.28 | +21.4% | -16.9% | -19.4% | -22.4% | 5.99 → 7.78 | 2/0 → 2/0 |
| 5 | 11.28 → 13.16 | +16.7% | -11.8% | -8.0% | -16.0% | 5.55 → 6.90 | 5/0 → 5/0 |
| 10 | 12.06 → 14.94 | +23.9% | -19.3% | -21.6% | -19.3% | 5.52 → 6.89 | 10/1 → 10/1 |
| 20 | 13.50 → 16.22 | +20.2% | -16.2% | -22.6% | -0.9% | 5.46 → 6.76 | 16/11 → 16/9 |
| 50 | 13.46 → 15.03 | +11.7% | -9.6% | -11.7% | -3.3% | 5.50 → 6.89 | 16/40 → 16/41 |
| 100 | 13.54 → 15.15 | +11.8% | -10.4% | -8.8% | -17.5% | 5.54 → 6.81 | 16/91 → 16/91 |

CPU 8의 최고 output throughput은 C=20의 16.22 token/s다. C=50과 100에서는 15.03~15.15 token/s로 더 늘지 않으므로 실용적인 포화점은 여전히 C=20이다. C=100의 E2E p95가 415.57초라는 점도 높은 client concurrency를 권장한다는 의미가 아님을 보여준다.

## 지표별 원인 분석

### C=1~2: CPU quota 완화가 decode 시간을 직접 줄임

waiting과 KV 포화가 없는 구간에서 baseline CPU 사용량은 약 5.99 cores로 6-core limit에 닿았다. limit 8에서는 평균 7.78 cores를 사용했고 output throughput은 21.4~24.8% 늘었다. TTFT뿐 아니라 TPOT p95도 20.6~22.4% 줄었으므로 단순 queue 감소가 아니라 prefill과 autoregressive decode 양쪽이 더 많은 CPU time을 받은 결과로 해석할 수 있다.

### C=10~20: 처리량과 tail latency가 함께 개선

C=10에서 평균 CPU는 `5.52 → 6.89`, output throughput은 23.9% 증가했고 E2E/TTFT/TPOT p95가 모두 약 19~22% 감소했다. C=20에서는 KV가 두 설정 모두 100%에 도달했지만 peak waiting이 `11 → 9`로 줄고 output throughput은 20.2% 증가했다. CPU quota 증가는 KV 용량을 늘리지 않아 peak running 16은 그대로지만, 실행 중 sequence를 더 빨리 처리해 일부 queue pressure를 줄였다.

### C=50~100: 서버 용량은 개선됐지만 queue 병목은 유지

고부하 throughput은 11.7~11.8% 늘고 E2E p95는 9.6~10.4% 줄었다. 그러나 peak running은 16, peak KV는 100%로 동일하며 peak waiting도 C=50에서 `40 → 41`, C=100에서 `91 → 91`이다. 즉 8-core limit은 각 batch의 service rate를 높였지만 KV/scheduler가 허용하는 동시 실행 폭을 바꾸지 않았다. CPU만 늘려서는 C=20 이후 throughput plateau와 수백 초의 TTFT를 제거할 수 없다.

### C=5 재측정: 최신 결과는 개선, 실행 간 변동은 큼

최초 CPU 8 C=5는 581.20초, 11.01 token/s로 baseline보다 2.3% 낮았다. 최신 재측정은 486.44초, 13.16 token/s로 최초 실행보다 19.5%, baseline보다 16.7% 높다. baseline 대비 E2E p95는 `38.92 → 34.32초`(-11.8%), TTFT p95는 `27.90 → 25.66초`(-8.0%), TPOT p95는 `422.60 → 355.07ms`(-16.0%)로 모두 개선됐다.

두 실행 모두 waiting 0, peak KV 32.8%, preemption/OOM 0이고 wall clock도 정상이므로 최초 악화를 무효 데이터로 볼 근거는 없다. 재측정은 CPU 6 보정 실험 뒤 다시 배포한 새 CPU 8 Pod에서 수행했으며 비교기가 image, args, resources가 동일함을 검증했다. 다만 process 재기동과 host thermal/background 상태 차이는 남는다. 두 CPU 8 표본의 단순 중앙값은 12.08 token/s로 baseline보다 7.2% 높지만 표본이 두 개뿐이다. CPU 8이 C=5에서 유리할 가능성은 높아졌지만 개선 폭을 확정하려면 최소 세 번 이상의 교차 실행이 필요하다.

## 자원과 안정성

| 지표 | CPU limit 6 | CPU limit 8 | 해석 |
|---|---:|---:|---|
| phase 평균 CPU의 평균 | 5.65 cores | 7.11 cores | 추가 quota가 실제 연산에 사용됨 |
| 전체 peak Pod RAM | 6.05GiB | 6.15GiB | CPU 8이 0.10GiB 높지만 6.5GiB limit 이내 |
| 총 preemption | 2 | 2 | KV pressure 자체는 해소되지 않음 |
| OOM kill / restart | 0 / 0 | 0 / 0 | 두 설정 모두 완주 안정성 확보 |

초기 CPU 8 matrix Pod의 실험 후 누적 cgroup 값은 `nr_throttled/nr_periods=17,626/44,527`, 약 39.6%였다. 새 Pod에서 C=5를 재측정한 직후의 누적값은 `2,048/12,032`, 약 17.0%였다. 두 값 모두 startup·warmup·smoke가 섞여 있고 phase 시작/종료 delta가 아니므로 A/B 변화율로 사용하지 않는다. 대신 9 OpenMP threads가 8-core quota 아래 있어 throttling 가능성이 남고 실행별 변동이 크다는 보조 증거로만 사용한다.

## 최종 권고

이 장비와 현재 모델·워크로드에서는 baseline 기본 overlay를 보존하고 `baseline-cpu8` overlay를 성능 실험용 권장값으로 사용한다. 10 vCPU 전부를 Pod limit으로 주지 않고 8만 할당해 Kind control-plane, kubelet, container runtime과 benchmark client가 사용할 여유를 남긴다.

CPU 8은 “가능한 유일한 최적화”가 아니다. 이번에 실제 검증한 한 필드 변경 중 가장 직접적인 개선이다. weight quantization, OpenMP thread/affinity, scheduler/KV 조합은 별도 변수를 바꾸므로 독립 A/B로 검증해야 한다. FP8 KV cache는 Apple M4/ARM64의 vLLM CPU backend가 요구 kernel을 지원하지 않아 적용 실패했으며, 상세 이력은 [FP8 KV 실패 리포트](03_FAILED_OPTIMIZATION_FP8_KV.md)에 보존돼 있다. MTP와 legacy capacity bundle의 효과·역효과는 [기존 최적화 리포트](04_OPTIMIZATION_FINAL_ANALYSIS.md)에서 비교한다.

후속으로 CPU limit 8을 고정한 채 MTP와 capacity bundle을 다시 2,100건 비교했다. 저동시성에서는 MTP가 유리했지만 지속적인 C≥10의 보수적 기본값은 baseline-cpu8이었으며, 상세 결과는 [CPU8 MTP·capacity bundle 분석 리포트](06_CPU8_MTP_KV_ANALYSIS.md)에 있다.

## 시간이 더 있다면

1. CPU 6과 8을 `6→8→6→8` 교차 순서로 각 3회 이상 실행하고 phase별 중앙값, IQR 또는 bootstrap 신뢰구간을 제시한다.
2. host 전원·온도·background process를 기록하고 동시성 순서를 무작위화해 C=5 tail 변동이 재현되는지 확인한다.
3. CPU limit 7·8·9를 탐색하고 OpenMP thread 수와 affinity를 limit에 맞추는 별도 A/B를 수행한다. 특히 현재 9 threads/8 quota의 잔여 throttling을 줄일 가능성이 있다.
4. high concurrency에서는 `max-num-seqs`, KV bytes, batched tokens를 grid search하되 처리량뿐 아니라 TTFT p95 SLO를 목적함수에 포함한다.
5. 향후 runner에 phase 시작/종료의 cgroup `nr_throttled`와 `throttled_usec` delta, host thermal/power proxy를 직접 저장해 원인 분석을 강화한다.

## 재현 명령

```bash
make deploy
make benchmark-baseline

make deploy-baseline-cpu8
make benchmark-baseline-cpu8

make benchmark-compare-cpu8
```

중단된 phase만 원본 보존 후 재측정하려면 다음과 같이 실행한다.

```bash
python3 benchmark/scripts/run_benchmark.py \
  --config benchmark/config/baseline-cpu8.json \
  --prompts benchmark/data/prompts.jsonl \
  --output benchmark/results/baseline-cpu8 \
  --resume \
  --rerun-concurrencies 10 \
  --rerun-reason "host suspension detected" \
  --max-new-phases 1
```
