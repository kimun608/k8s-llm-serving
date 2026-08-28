# Baseline 단일 변경 실험: CPU limit 6 → 8

이 문서는 배포와 측정 전에 작성한 실험 계획이다. 기존 baseline에서 Kubernetes container CPU limit 한 필드만 `6`에서 `8`로 변경하고 같은 700-request matrix를 재실행한다.

## 가설

Docker Desktop VM은 Apple M4의 10 vCPU를 모두 제공하지만 baseline Pod의 cgroup quota는 6 cores다. baseline C=1 평균 CPU가 5.99 cores였고 동일 resource limit을 사용한 장시간 실행에서 `cpu.max=600000 100000`과 높은 throttling 빈도를 확인했다. vLLM CPU backend는 auto OpenMP binding으로 9개 compute core를 선택하므로 6-core quota가 계산을 제한하고 있을 가능성이 크다.

CPU limit을 8로 늘리면 Kind control-plane·kubelet·container runtime을 위한 약 2 vCPU를 남기면서 vLLM quota를 완화할 수 있다. 예상 효과는 output token throughput 증가와 E2E/TPOT 감소다. 다만 C≥20의 512MiB KV 포화는 그대로이므로 peak running 16 제한 자체는 없어지지 않을 수 있다.

## 유일한 serving 변경

```diff
 resources:
   limits:
-    cpu: "6"
+    cpu: "8"
```

다음은 변경하지 않는다.

- model/checkpoint와 image
- BF16 dtype, max model length 2,048
- MTP off
- KV cache 512MiB
- max sequences 20, max batched tokens 2,048
- Automatic Prefix Caching off
- CPU request 4, memory request/limit 4Gi/6656Mi
- replicas, Service, probes, worker placement
- 고정 100 prompts, prompt 순서와 SHA-256
- 출력 64 tokens, sampling, warmup/cooldown
- 동시성 `1, 2, 5, 10, 20, 50, 100`; C별 총 요청 100건

Kustomize rendered output은 baseline과 CPU limit 외 차이가 없는지 배포 전에 구조적으로 비교한다.

## 판단 지표

- 정확성: 700/700 success, client/server token counter 일치
- 우선 지표: output token/s, TPOT p50/p95
- 사용자 체감: E2E와 TTFT p50/p95
- 병목: peak running/waiting, KV usage, average Pod CPU
- 안전성: peak RAM, preemption, OOM/restart, metric scrape error

CPU limit 증가는 resource right-sizing이므로 이론적 `8/6`만큼 선형 개선된다고 가정하지 않는다. Apple M4의 heterogeneous cores, memory bandwidth, KV 포화, Docker/Kubernetes overhead 때문에 실제 개선 폭은 더 작을 수 있다. 각 동시성의 실측치로만 결론을 낸다.

## 실행 순서

```bash
make deploy-baseline-cpu8
make smoke
make benchmark-baseline-cpu8
make benchmark-compare-cpu8
```

공개된 기존 결과를 덮어쓰지 않고 재현하려면 새 `RESULTS_ROOT`를 지정한다.

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-cpu8.XXXXXX)"
make benchmark-baseline-cpu8 RESULTS_ROOT="$rerun_root"
```

## 결과 위치

```text
benchmark/results/
├── baseline/                 # 기존 CPU limit 6 결과
├── baseline-cpu8/            # 신규 CPU limit 8 결과
└── comparison-cpu8/          # 자동 before/after 표와 그래프
```

정식 측정 후 이 문서에 실측 결론을 추가하고 `reports/05_BASELINE_CPU8_ANALYSIS.md`에 원인과 권고를 정리한다.

## 실측 결과

정식 비교는 설정별 700건, 합계 1,400건을 모두 성공했다. CPU limit 외 serving 설정과 benchmark workload가 동일하고 client/server token counter가 일치함을 자동 비교기가 검증했다.

| C | Output tok/s 6 → 8 | 변화 | E2E p95 변화 | TTFT p95 변화 |
|---:|---:|---:|---:|---:|
| 1 | 5.16 → 6.44 | +24.8% | -17.8% | -16.2% |
| 2 | 7.64 → 9.28 | +21.4% | -16.9% | -19.4% |
| 5 | 11.28 → 13.16 | +16.7% | -11.8% | -8.0% |
| 10 | 12.06 → 14.94 | +23.9% | -19.3% | -21.6% |
| 20 | 13.50 → 16.22 | +20.2% | -16.2% | -22.6% |
| 50 | 13.46 → 15.03 | +11.7% | -9.6% | -11.7% |
| 100 | 13.54 → 15.15 | +11.8% | -10.4% | -8.8% |

최신 정식 결과의 고정 출력 44,800 tokens 기준 합산 output throughput은 `9.74 → 11.66 token/s`로 19.7% 증가했고 phase 시간 합은 16.5% 감소했다. 사용자 요청으로 C=5를 한 번 더 실행한 결과는 `11.01 → 13.16 token/s`, E2E p95 `52.59 → 34.32초`로 개선됐다. CPU 6 baseline과 비교하면 처리량 +16.7%, E2E p95 -11.8%다.

다만 유효한 CPU 8 C=5 두 표본 사이의 처리량 차이가 19.5%다. 첫 실행은 baseline 대비 -2.3%, 재측정은 +16.7%였고 두 값의 단순 중앙값은 baseline 대비 +7.2%다. 따라서 최신 자동 비교는 재측정값을 사용하되 C=5의 개선 폭은 3회 이상 반복하기 전까지 확정하지 않는다.

장시간 실행 중 host가 중단된 초기 CPU 6 C=2와 CPU 8 C=10 표본은 결과에서 제외하되 `benchmark/results/*/excluded/`에 원시 데이터와 이유를 보존했다. 확인을 위해 교체한 최초 CPU 8 C=5 표본도 같은 위치에 보존하되 무효 표본으로 취급하지 않는다. 재측정된 정식 phase는 wall clock과 monotonic timer 차이가 모두 0.05초 이하다.

최종 판단은 **현재 장비에서 CPU 8 overlay를 권장하되, C=20 이후 KV 100%·waiting queue 병목은 별도 최적화 대상으로 남긴다**는 것이다. 전체 수치, 예외 표본과 원인 분석은 [CPU 8 분석 리포트](../../reports/05_BASELINE_CPU8_ANALYSIS.md)를 본다.
