# Local CPU vLLM on Kind Kubernetes

Apple M4에서 GPU 없이 MTP layer가 포함된 Qwen3.5-0.8B를 vLLM CPU 런타임으로 서빙하는 프로젝트입니다. 클러스터, 모델 서빙, 부하 측정의 책임을 폴더별로 분리했습니다.

```text
project_process/
├── k8s/                         # Kind 클러스터 설치와 노드 구성
│   ├── README.md
│   ├── kind/cluster.yaml
│   └── scripts/
├── model_serving/               # 모델 이미지와 Kubernetes 애플리케이션
│   ├── README.md
│   ├── Dockerfile
│   ├── k8s/
│   │   ├── base/
│   │   └── overlays/baseline/
│   └── scripts/
├── benchmark/                   # 공개 데이터셋 기반 100-request 부하 측정
├── optimization/                # CPU limit·MTP·KV/maxseq 분리 실험
├── results/                     # 실제 실행 결과
├── reports/                     # 통합 분석 문서
└── Makefile                     # 전체 실행 진입점
```

## 먼저 읽을 문서

> **최종 제출본:** [논문형 최종 보고서](reports/final-report.md)

1. [Kubernetes 클러스터 설치·이미지 로드](k8s/README.md)
2. [vLLM 모델 이미지 빌드·K8s 배포](model_serving/README.md)
3. [100-request 베이스라인 벤치마크](benchmark/README.md)
4. [베이스라인 실측 분석 리포트](reports/02_BASELINE_BENCHMARK.md)
5. [MTP·capacity bundle 최적화 적용 및 재측정](optimization/README.md)
6. [실패 기록: Apple M4에서 FP8 KV cache](reports/03_FAILED_OPTIMIZATION_FP8_KV.md)
7. [최적화 before/after 최종 분석](reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)
8. [단일 변경 검증: CPU limit 6 → 8](reports/05_BASELINE_CPU8_ANALYSIS.md)
9. [CPU 8 고정: Baseline vs MTP vs capacity bundle 분석](reports/06_CPU8_MTP_KV_ANALYSIS.md)
10. [CPU8 KV×max-num-seqs 2×2 분리 실험](optimization/cpu8-factorial/README.md)
11. [전체 8개 variant 종합 비교](benchmark/results/comparison-all/REPORT.md)
12. [전체 수치·감사 근거 상세본](reports/07_FINAL_COMPREHENSIVE_ANALYSIS.md)

## master와 worker의 관계

Kind에서 master 역할은 `project-process-control-plane`, worker 역할은 `project-process-worker`라는 별도 노드 컨테이너가 담당합니다. 애플리케이션 이미지 이름에 master/worker를 넣는 것이 아니라 동일한 이미지를 각 노드의 containerd에 로드합니다. 이후 Deployment의 nodeSelector와 Kubernetes 스케줄러가 vLLM Pod를 worker에 배치합니다.

현재 검증된 상태:

- control-plane: `Ready`, IP `172.18.0.3`
- worker: `Ready`, IP `172.18.0.2`
- 두 노드 모두 Docker의 `kind` 네트워크에 연결
- 두 노드 모두 `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0` 이미지를 로드하도록 구성
- vLLM Pod는 worker에서 `Running 1/1`

직접 확인하려면 다음 명령을 사용합니다.

```bash
make verify-cluster
make status
```

## 전체 실행 순서

Docker Desktop을 먼저 실행합니다.

```bash
make preflight
make install-kind
make image
make cluster
make load
make verify-cluster
make deploy
make wait
make status
make smoke
```

새 환경에서는 `make all`로 smoke test 직전까지 한 번에 실행할 수 있습니다. 현재 클러스터를 제거하려면 `make clean-cluster`를 사용합니다. 이 명령은 로컬 모델 이미지는 제거하지 않습니다.

완료된 CPU8 2×2 단일 변수 실험을 재현하고, 저장소의 8개 결과를 다시 검증하려면 다음 진입점을 사용합니다. 각 benchmark target은 동시성 7단계별 100건, 총 700건을 실행합니다.

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-results.XXXXXX)"

make deploy-mtp-kv768-cpu8
make smoke
make benchmark-mtp-kv768-cpu8 RESULTS_ROOT="$rerun_root"

make deploy-mtp-seq24-cpu8
make smoke
make benchmark-mtp-seq24-cpu8 RESULTS_ROOT="$rerun_root"

# 아래 명령은 저장소에 보존한 8개 완료 결과를 검증한다.
make benchmark-compare-all
make validate-docs
```

제출용 결과를 보존하는 `RESULTS_ROOT` 사용법과 전체 8개 variant가 필요한 비교 조건은 [benchmark 실행 문서](benchmark/README.md)에 설명돼 있습니다.

컨테이너·클러스터·배포 결과는 [1단계 리포트](reports/01_CONTAINER_CLUSTER_DEPLOYMENT.md), 최초 700건 부하 측정은 [베이스라인 리포트](reports/02_BASELINE_BENCHMARK.md)에 기록돼 있습니다. CPU6/CPU8 baseline·MTP·capacity bundle과 CPU8의 KV-only·maxseq-only까지 총 8개 variant를 동시성별 100건씩 측정해 `5,600/5,600`건이 성공했습니다. 전체 제출 결론은 [논문형 최종 보고서](reports/final-report.md), factor와 수치는 [comparison-all](benchmark/results/comparison-all/REPORT.md), 원시는 [benchmark/results](benchmark/results/)에 보관합니다.

기존 `mtp-kv-tuned*`는 재현성을 위해 이름을 유지한 legacy artifact ID이며, 실제로는 KV `512→768MiB`와 `max-num-seqs` `20→24`를 함께 바꾼 capacity bundle입니다. 분리 실험에서 KV-only는 C≥10의 peak running 최대값을 `5→8`, peak waiting 최대값을 3건 줄였지만 C=10·20 throughput은 `-10.2%`, `-10.4%`였습니다. Maxseq-only는 peak running/peak waiting을 바꾸지 않았고 C=5∼100 throughput도 `-0.4∼-5.4%`로 개선되지 않았습니다. 따라서 지속적인 C≥10의 보수적 기본값은 `baseline-cpu8`이고, `mtp-cpu8`은 C≤5의 throughput 후보로 TTFT/E2E SLO별 반복 검증이 필요합니다. Capacity를 키운 두 설정은 속도 최적화로 채택하지 않습니다.
