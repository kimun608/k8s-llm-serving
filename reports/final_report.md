# 로컬 CPU Kubernetes 환경에서의 vLLM 추론 서빙 최적화

> CPU8에서 MTP2, KV cache 용량과 FP8 KV cache를 독립 검증한 실험

이 보고서는 최종 실험의 설계, 결과와 적용 조건만 정리한다. Apple M4/ARM64 환경에서 수행한 기존 실험은 [선행 연구: `feature/model-compare`](https://github.com/kimun608/k8s-llm-serving/tree/feature/model-compare)로 지정한다. 전체 phase 수치와 검증 기록은 [자동 비교 보고서](../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/REPORT.md)에 보존한다.

## 초록

Docker Desktop의 Linux/x86_64 환경에 2-node Kind Kubernetes를 구성하고, CPU-only vLLM으로 `Qwen/Qwen3.5-0.8B`를 서빙했다. 공개 데이터셋 네 종류에서 25건씩 선택한 100개 prompt를 최대 동시 요청 `1, 2, 5, 10, 20, 50, 100`으로 처리했다. FP8 KV cache는 [선행 연구](https://github.com/kimun608/k8s-llm-serving/tree/feature/model-compare)의 Apple M4/ARM64 CPU backend에서 지원 kernel이 없어 기동에 실패했기 때문에, Windows/x86_64 PC에서 다시 구성해 정상 기동을 확인한 뒤 정식 비교에 포함했다.

CPU8·MTP off·KV cache 512MiB를 기준으로 MTP2, KV cache 768MiB, FP8 KV cache를 각각 단독 적용했다. 고부하에서 개선된 KV cache 768MiB와 FP8 KV cache만 마지막에 결합했다. 정식 요청 `3,500/3,500`과 별도 FP8 검증 요청 `40/40`이 성공했다.

최대 20/50/100건을 동시에 유지한 구간에서 MTP2는 처리량이 평균 `30.05%` 낮아졌고, KV cache 768MiB와 FP8 KV cache는 각각 `9.47%`, `5.40%` 높아졌다. KV cache 768MiB+FP8은 기준보다 `9.53%` 높았지만 KV cache 768MiB 단독과는 `0.05%` 차이에 그쳤다. 따라서 추가 메모리를 사용할 수 있으면 KV cache 768MiB를 기본값으로 선택하고, KV cache 할당량을 늘릴 수 없으면 같은 512MiB에서 수용량을 높이는 FP8을 대안 후보로 둔다. MTP2는 최대 1/2건 동시 유지에서 가장 빨랐지만 현재 CPU와 KV 수용량에서는 고부하 대기열을 감당하지 못했다.

## 1. 실험 구성

### 1.1 환경과 공통 조건

| 항목 | 값 |
|---|---|
| Host | Windows 11, AMD Ryzen 7 7800X3D |
| Container / Kubernetes | Docker Desktop Linux/x86_64, Kind 2-node |
| Runtime / Model | vLLM `0.26.0+cpu`, `Qwen/Qwen3.5-0.8B` |
| Pod 제한 | CPU 8 cores, 메모리 8GiB |
| 공통 설정 | max-model-len 2,048, max-num-seqs 20, max-batched-tokens 2,048 |
| Workload | 100 prompts, 요청당 output 64 tokens |
| 동시 요청 | 최대 1, 2, 5, 10, 20, 50, 100건 |

모든 설정은 같은 model image, prompt 순서, CPU limit과 scheduler 상한을 사용했다. Prefix caching은 꺼서 반복 실행의 cache hit가 결과에 섞이지 않도록 했다.

### 1.2 데이터셋 선택

서로 다른 길이와 형태의 요청을 만들기 위해 GSM8K, HumanEval, TruthfulQA와 LongBench Qasper에서 각각 25건을 선택했다.

| 데이터셋 | 선택 수 | 요청 특성 |
|---|---:|---|
| GSM8K | 25 | 수학 추론 |
| HumanEval | 25 | Python 코드 완성 |
| TruthfulQA | 25 | 짧은 사실 질의 |
| LongBench Qasper | 25 | 모델 입력 길이에 맞춰 자른 긴 문서 질의 |

100건을 다시 만들어도 같은 항목이 선택되도록 고정 난수값 `20260828`을 사용했다. 네 데이터셋이 똑같은 난수 순서를 공유하지 않도록 데이터셋마다 서로 다른 고정값 `20260828/20261828/20262828/20263828`을 사용했다. 각 데이터셋 안에서는 중복 없이 25건을 뽑았다.

선택한 요청은 `GSM8K → HumanEval → TruthfulQA → Qasper` 순서로 한 건씩 번갈아 배치했다. 따라서 특정 데이터셋 25건이 한 구간에 몰리지 않고 모든 부하 단계가 같은 순서의 100건을 처리한다. Qasper 문맥은 요청 전체가 2,048-token 모델 한도 안에 들어오도록 미리 정한 다섯 길이로 잘랐다. Revision은 내려받을 데이터셋 버전을 고정하고, SHA-256은 원본 파일이 바뀌지 않았는지 확인하는 값이다. 생성 과정은 [prepare_dataset.py](../benchmark/scripts/prepare_dataset.py), 원본 버전과 hash는 [source-manifest.json](../benchmark/data/source-manifest.json)에 있다.

### 1.3 부하 방식

각 설정은 100개 요청 중 최대 `1, 2, 5, 10, 20, 50, 100`건을 동시에 유지하며 처리했다. 한 요청이 끝나면 다음 요청을 제출하므로 각 단계는 같은 100건을 한 번씩 완료한다. 설정 하나당 `100건 × 7단계 = 700건`이다.

전체 응답 시간(E2E)은 요청 시작부터 응답 완료까지, 첫 token 시간(TTFT)은 요청 시작부터 첫 token 수신까지의 시간이다. 두 값은 streaming client에서 측정했고, 실행 중 요청·대기 요청·KV 사용률은 vLLM `/metrics`, CPU와 메모리는 Pod cgroup에서 1초 간격으로 수집했다.

### 1.4 비교한 설정

| 설정 | MTP2 | KV cache | 역할 |
|---|---|---|---|
| CPU8 기준 | off | 512MiB, BF16 | 공통 기준 |
| MTP2 단독 | on | 512MiB, BF16 | MTP 효과 |
| KV cache 증설 | off | 768MiB, BF16 | 추가 KV 메모리 효과 |
| FP8 KV cache | off | 512MiB, FP8 | 같은 512MiB에서 압축 효과 |
| KV cache 증설+FP8 | off | 768MiB, FP8 | 개선된 두 옵션의 결합 |

FP8 KV cache는 [선행 연구](https://github.com/kimun608/k8s-llm-serving/tree/feature/model-compare)의 `Apple M4 → Docker Linux/ARM64` 환경에서 먼저 적용했지만, vLLM CPU backend가 `FP8 KV cache on CPU requires x86 with AVX-512 or AMX` 오류를 내며 API server 초기화 전에 종료됐다. 이는 성능이 낮았던 결과가 아니라 해당 ARM64 backend의 호환성 실패다. 이후 Windows PC의 `AMD Ryzen 7 7800X3D → Docker Linux/x86_64` 환경에서 같은 FP8 옵션을 적용했고 server startup과 C20 gate를 통과했다. FP8 단독과 KV cache 768MiB+FP8은 각각 정식 700건과 별도 gate 20건을 모두 완료했다. 상세 증거는 [Apple ARM64 실패 기록](results/03_FAILED_OPTIMIZATION_FP8_KV.md), [Windows FP8 시작 로그](../benchmark/results-windows-cpu8-factors-20260830/startup-evidence/baseline-cpu8-fp8/startup.log)와 [C20 검증 결과](../benchmark/results-windows-cpu8-factors-20260830/validation-gates/baseline-cpu8-fp8-c20/REPORT.md)에 보존했다.

먼저 기준과 세 단독 옵션을 `2,800건` 실행했다. 최대 20/50/100건 동시 유지에서 MTP2는 제외하고, 개선된 KV cache 768MiB와 FP8 KV cache만 결합해 `700건`을 추가했다.

## 2. 결과

### 2.1 기준 설정의 포화

| 최대 동시 유지 | 출력 tok/s | 전체 응답 p95 | 첫 token p95 | 최대 실행 중 / 대기 요청 | 최대 KV 사용률 |
|---:|---:|---:|---:|---:|---:|
| 1 | 22.29 | 3.57s | 1.04s | 1 / 0 | 7.5% |
| 2 | 39.04 | 3.84s | 1.19s | 2 / 0 | 13.4% |
| 5 | 68.82 | 5.56s | 2.63s | 5 / 0 | 32.8% |
| 10 | 94.39 | 7.77s | 4.05s | 10 / 1 | 64.2% |
| 20 | 102.59 | 17.43s | 9.28s | 16 / 11 | 100.0% |
| 50 | 101.74 | 34.51s | 27.32s | 16 / 41 | 100.0% |
| 100 | 105.19 | 58.06s | 52.00s | 16 / 90 | 100.0% |

최대 실행 중 요청과 최대 대기 요청은 1초 시계열에서 각각 구한 값이라 반드시 같은 시점의 상태는 아니다.

최대 20건 동시 유지부터 KV가 100%에 도달하고 실행 중 요청은 16에서 더 늘지 않았다. 최대 50건과 100건에서도 처리량은 약 102~105 tok/s로 같고 대기 요청만 증가했다. 이 구간에서는 요청을 더 보내도 실제 동시 처리 폭이 늘지 않는다.

### 2.2 설정별 처리량

| 최대 동시 유지 | CPU8 기준 | MTP2 단독 | KV 768MiB | FP8 512MiB | KV 768MiB+FP8 |
|---:|---:|---:|---:|---:|---:|
| 1 | 22.29 | **30.43** | 22.35 | 22.45 | 22.42 |
| 2 | 39.04 | **47.74** | 39.00 | 39.10 | 38.83 |
| 5 | 68.82 | **71.03** | 68.75 | 69.42 | 69.37 |
| 10 | **94.39** | 71.32 | 93.25 | 91.58 | 93.70 |
| 20 | 102.59 | 71.36 | **113.06** | 109.18 | 112.86 |
| 50 | 101.74 | 72.78 | 112.57 | 107.56 | **113.23** |
| 100 | 105.19 | 72.34 | **113.14** | 109.44 | 112.86 |

![설정별 output throughput](../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/output-throughput.svg)

### 2.3 독립 옵션의 효과

| 적용 옵션 | KV token 수용량 | 최대 20/50/100건 처리량 변화 | 최대 실행 중 요청 | 판정 |
|---|---:|---:|---:|---|
| MTP2 | 9,137 | **-30.05%** | 5 | 저동시성 전용 후보 |
| KV cache 512→768MiB | 29,842 | **+9.47%** | 20 | 고부하 기본값 |
| BF16→FP8 KV cache | 30,720 | **+5.40%** | 18 | KV 할당량 증설 불가 시 후보 |
| KV 768MiB+FP8 | 46,284 | **+9.53%** | 20 | 최대 수용량이 필요할 때 후보 |

![기준 대비 옵션별 효과](../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/factor-effects.svg)

정식 `3,500/3,500`건과 FP8 검증 `40/40`건이 모두 성공했다. Client와 server의 token 합계가 일치했고 원시 결과를 다시 집계한 값도 summary와 같았다. HTTP 오류, Pod restart와 OOM은 없었다.

## 3. 논의와 적용 조건

### 3.1 메모리를 더 할당할 수 없는 경우

FP8 KV cache는 512MiB를 그대로 사용하면서 token 수용량을 `19,894→30,720`으로 54.4% 늘렸다. 그 결과 포화 구간 처리량이 평균 5.40% 증가했다. 따라서 KV cache 할당량을 늘릴 수 없는 조건에서 서빙 성능 대안 후보가 된다.

다만 FP8이 Pod 전체 메모리를 자동으로 줄이는 것은 아니다. 이번 측정의 최대 Pod 메모리는 기준 6.024GiB, FP8 6.273GiB였다. 같은 512MiB에서 더 많은 요청 상태를 저장했다는 의미이며, 적용 전 응답 품질 평가는 별도로 필요하다.

### 3.2 메모리를 더 할당할 수 있는 경우

KV cache를 512→768MiB로 늘리면 token 수용량이 `19,894→29,842`, 최대 실행 중 요청이 `16→20`으로 증가했다. 최대 20/50/100건 동시 유지의 처리량은 평균 9.47%, 전체 응답 p95는 8.84% 개선됐다. 추가 메모리를 사용할 수 있는 고부하 환경에서는 이 설정이 가장 단순한 기본값이다.

KV cache 768MiB에 FP8까지 적용하면 수용량은 46,284 tokens로 더 늘지만 처리량은 KV cache 768MiB 단독보다 평균 0.05%만 높았다. KV cache 768MiB만으로 이미 `max-num-seqs=20`에 도달했기 때문에 FP8으로 늘어난 수용량이 동시 실행 폭이나 처리량 확대에는 사용되지 못했다. 다음 병목이 스케줄러 상한인지 CPU 처리율인지는 별도 실험이 필요하다.

### 3.3 MTP2가 저부하에서만 개선된 이유

MTP2는 대기 요청이 없는 최대 1/2건 동시 유지에서 처리량을 36.5%, 22.3% 높였다. 그러나 최대 10건부터 MTP2 처리량이 기준보다 낮아졌다. 기준 설정도 최대 20건에서 실행 중/대기 요청 `16/11`로 포화됐지만, MTP2는 KV token 수용량이 `19,894→9,137`로 줄어 실행 중 요청이 5에 제한됐고 최대 20건의 대기 요청은 15였다. CPU도 약 7.94/8 cores를 사용해 저부하의 이득이 고부하 대기열 증가를 상쇄하지 못했다.

따라서 현재 결과는 MTP 자체가 항상 느리다는 뜻이 아니다. 줄어든 동시 실행 폭과 제안·검증 과정의 CPU 비용이 함께 관측됐으며, 이번 실험은 두 원인을 분리하지 못했다. GPU의 높은 병렬 처리와 최적화된 MTP kernel은 이 비용을 더 잘 상쇄할 가능성이 있다. 반대로 GPU의 기본 batching이 이미 효율적이면 이득이 작을 수도 있으므로, 동일 GPU 수·KV 수용량·max-seqs에서 MTP off/on을 다시 비교해야 한다.

![설정별 실행 중 요청과 대기 요청](../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/scheduler-pressure.svg)

### 3.4 최종 선택

| 운영 조건 | 선택 |
|---|---|
| 최대 20건 이상 지속, 추가 메모리 가능 | **CPU8 / MTP off / KV cache 768MiB / BF16** |
| 최대 20건 이상 지속, KV 할당량 증설 불가 | **CPU8 / MTP off / KV cache 512MiB / FP8 후보** |
| 처리량보다 최대 KV 수용량 우선 | **KV cache 768MiB + FP8 후보** |
| 최대 1/2건 중심 | **MTP2 후보** |
| 20건을 넘는 요청이 지속됨 | Admission control 또는 replica 확장 |

## 4. 한계와 후속 실험

### 4.1 한계

1. 각 설정과 동시 요청 조합을 한 번씩 실행해 실행 순서와 host 상태의 영향을 완전히 제거하지 못했다.
2. KV cache 768MiB+FP8은 단독 결과를 본 뒤 선택한 조합이며 전체 조합을 모두 시험한 것은 아니다.
3. 포화점은 현재 100개 workload, output 64 tokens와 `max-num-seqs=20`에 종속된다.
4. 단일 host와 Pod 1개 결과이며 실제 다중 replica와 GPU 환경은 측정하지 않았다.
5. FP8의 serving 성공은 검증했지만 task 정답률과 응답 품질은 평가하지 않았다.

### 4.2 후속 실험

1. 기준, KV cache 768MiB, FP8과 결합 설정을 무작위 순서로 3~5회 반복한다.
2. KV cache 용량과 `max-num-seqs`를 분리해 다음 병목을 확인한다.
3. MTP off/on에 같은 KV token 수용량을 주고 CPU와 메모리를 단계적으로 늘려 비교한다.
4. 같은 조건을 GPU에서 반복해 MTP 효과와 최적화 kernel의 영향을 확인한다.
5. FP8 설정의 task 품질과 장문·한국어·실제 arrival 패턴을 평가한다.

## 5. 결론

KV cache 할당량을 늘릴 수 없으면 FP8이 같은 512MiB에서 동시 수용량을 높이는 대안이다. 추가 메모리가 가능하면 KV cache 768MiB가 실제 실행 중 요청을 16→20으로 늘려 가장 큰 고부하 처리량 개선을 냈다. 두 옵션을 함께 적용해도 실행 상한 20을 넘지 못해 추가 처리량은 거의 없었다.

MTP2는 최대 1/2건 동시 유지에서 가장 큰 이득을 보였지만 현재 CPU와 KV 수용량에서는 실행 중 요청 5와 대기열 증가로 고부하 성능이 낮아졌다. GPU 또는 더 큰 CPU·메모리 환경에서 이 저부하 이득이 고부하까지 유지되는지는 동일 자원 조건의 실험으로 확인해야 한다.

## 6. 대규모 GPU Kubernetes production 전환

이번 CPU 실험의 최적 수치와 설정을 GPU 환경에 그대로 적용할 수는 없다. 대신 같은 workload에서 한 번에 한 요인만 바꾸고 처리량, 지연, 대기열과 KV 수용량을 함께 판단한 절차는 유지한다.

### 6.1 유지할 원칙과 다시 측정할 값

| 영역 | 유지할 원칙 | GPU production에서 다시 설계·측정할 값 |
|---|---|---|
| 실험 | 동일 workload, 한 번에 한 요인 변경, 실패 결과 보존 | 실제 traffic, open-loop 부하, 3회 이상 반복과 비용·SLO 비교 |
| 지표 | 처리량과 TTFT·TPOT·대기·KV를 함께 판단 | GPU 사용률, HBM bandwidth, power, NCCL와 rank별 상태 |
| 배포 | image·model revision 고정, probe와 rollback | GPU operator/device plugin, topology·MIG, model weight cache |
| 확장 | 포화점과 queue를 확인한 뒤 scale-out | waiting·TTFT·KV 기반 autoscaling과 긴 model load 시간 |
| 가용성 | replica 상태와 복구 여부 검증 | node·zone 분산, RollingUpdate, PDB와 강제 장애 시험 |

로컬 실험에서 확인한 증감률보다 병목을 분리하는 방법을 이전하고, GPU·모델·traffic별 최적값은 다시 측정한다.

### 6.2 TP2와 replica2

총 GPU가 2개일 때 선택 기준은 요청이 복잡한지가 아니라 모델이 GPU 1개에 들어가는지, KV 여유, 전체 처리량, GPU 간 연결과 장애 격리다.

| 조건 | TP2 × replica1 | TP1 × replica2 |
|---|---|---|
| 우선 선택 | 모델이 GPU 1개에 들어가지 않거나 weight sharding이 필요함 | 모델이 GPU 1개에 들어가고 전체 처리량·장애 격리가 중요함 |
| KV 관점 | GPU별 weight 점유가 줄어 KV 여유가 생길 수 있음 | replica마다 독립 KV cache를 가짐 |
| 비용 | GPU 간 통신과 topology에 의존 | model weight를 두 번 적재하고 routing이 필요함 |
| 장애 | GPU 하나가 실패하면 논리 replica 전체가 중단 | node를 분리하면 다른 replica가 요청을 수용 가능 |
| 판단 | 병렬화이며 고가용성 구성이 아님 | 모델이 들어간다면 기본 비교점 |

TP2가 weight 공간을 줄여 KV 여유를 만들 수는 있지만 KV 수용량이 정확히 두 배가 된다고 가정할 수는 없다. 시작 로그의 GPU KV cache size와 maximum concurrency, 실행 중 preemption을 같은 총 GPU 수로 직접 비교해야 한다. TP2와 replica 수준 이중화가 모두 필요하면 최소 `TP2 × 2 replicas = 4 GPUs`가 필요하다.

### 6.3 llm-d를 적용할 조건

| Routing | 적용 조건 |
|---|---|
| Round-robin | 요청 길이와 queue가 비슷하고 단순한 분산이 우선일 때 |
| llm-d load-aware | 요청 길이·대기열 편차가 커서 덜 바쁜 replica를 선택해야 할 때 |
| llm-d prefix-aware | 공통 system prompt, 동일 문서 질의, multi-turn처럼 반복 prefix가 많고 APC를 사용할 때 |

llm-d Router는 여러 Pod의 KV cache를 합치는 기능이 아니다. queue와 KV 상태를 보고 덜 바쁜 Pod 또는 필요한 prefix cache가 남은 Pod로 요청을 보내는 역할이다. 이번 실험은 replica 1개이고 APC를 껐으므로 llm-d 효과를 측정하지 않았으며, production trace에서 round-robin과 별도로 비교해야 한다.

### 6.4 KV·scheduler, autoscaling과 고가용성

1. 실제 입력·출력 길이와 SLO에 맞춰 `max-model-len`과 chunked prefill 조건을 고정한다.
2. 시작 로그의 KV 수용량과 실행 중 preemption을 확인한 뒤 `max-num-seqs`와 `max-num-batched-tokens`를 각각 조정한다.
3. 출력 처리량만 보지 않고 TTFT·TPOT, 대기 요청, KV 사용률과 preemption을 함께 평가한다.
4. CPU 사용률만으로 확장하지 않고 waiting requests, TTFT 위반률, in-flight tokens와 KV pressure를 autoscaling 지표로 사용한다.

Replica는 topology spread와 anti-affinity로 node·zone에 분산하고 startup/readiness probe, RollingUpdate와 warm weight cache를 함께 설계한다. PDB는 drain 같은 계획된 중단에서 동시 중단 수를 제한할 뿐 GPU나 node 고장을 막지 않으므로 replica 분산과 실제 장애 시험이 별도로 필요하다.

## 7. 재현성과 산출물

```powershell
# 도구 설치, image, cluster, 배포와 smoke test
.\project.ps1 all
.\project.ps1 smoke

# 기준과 세 단독 옵션
$resultsRoot = Join-Path $PWD 'benchmark\results-windows-cpu8-factors-rerun'
$core = @(
  'baseline-cpu8',
  'mtp-cpu8',
  'baseline-kv768-cpu8',
  'baseline-cpu8-fp8'
)
.\benchmark\scripts\run-windows-suite.ps1 -ResultsRoot $resultsRoot -Variants $core
.\project.ps1 benchmark-compare-windows-cpu8-factors -ResultsRoot $resultsRoot

# 개선된 두 옵션의 조합
.\benchmark\scripts\run-windows-suite.ps1 `
  -ResultsRoot $resultsRoot -Variants @('baseline-kv768-fp8-cpu8')
.\project.ps1 benchmark-compare-windows-cpu8-factors -ResultsRoot $resultsRoot
```

- [전체 자동 비교](../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/REPORT.md)
- [35개 phase 비교 CSV](../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/comparison.csv)
- [Suite manifest](../benchmark/results-windows-cpu8-factors-20260830/suite-manifest.json)
- [원시 결과](../benchmark/results-windows-cpu8-factors-20260830/)

## 참고문헌

1. [vLLM MTP](https://docs.vllm.ai/en/v0.26.0/features/speculative_decoding/mtp/)
2. [vLLM Quantized KV Cache](https://docs.vllm.ai/en/v0.26.0/features/quantization/quantized_kvcache/)
3. [vLLM Optimization and Tuning](https://docs.vllm.ai/en/v0.26.0/configuration/optimization/)
4. Woosuk Kwon et al., [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180), SOSP 2023.
5. [vLLM Parallelism and Scaling](https://docs.vllm.ai/en/v0.26.0/serving/parallelism_scaling/)
6. [llm-d Request Scheduler](https://llm-d.ai/docs/0.8/architecture/core/router/epp/scheduling)
7. [Kubernetes Horizontal Pod Autoscaling](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
8. [Kubernetes Pod Topology Spread Constraints](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/)
9. [Kubernetes Disruptions and PodDisruptionBudget](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
10. [선행 연구: Apple M4/ARM64 CPU Kubernetes 실험 (`feature/model-compare`)](https://github.com/kimun608/k8s-llm-serving/tree/feature/model-compare)
