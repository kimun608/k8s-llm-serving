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
├── optimization/                # MTP·KV 최적화 실험 설계와 절차
├── results/                     # 실제 실행 결과
├── reports/                     # 통합 분석 문서
└── Makefile                     # 전체 실행 진입점
```

## 먼저 읽을 문서

1. [Kubernetes 클러스터 설치·이미지 로드](k8s/README.md)
2. [vLLM 모델 이미지 빌드·K8s 배포](model_serving/README.md)
3. [100-request 베이스라인 벤치마크](benchmark/README.md)
4. [베이스라인 실측 분석 리포트](reports/02_BASELINE_BENCHMARK.md)
5. [MTP·KV 최적화 적용 및 재측정 계획](optimization/README.md)
6. [실패 기록: Apple M4에서 FP8 KV cache](reports/03_FAILED_OPTIMIZATION_FP8_KV.md)
7. [최적화 before/after 최종 분석](reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)

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

컨테이너·클러스터·배포 결과는 [1단계 리포트](reports/01_CONTAINER_CLUSTER_DEPLOYMENT.md), 700건 부하 측정 결과는 [베이스라인 리포트](reports/02_BASELINE_BENCHMARK.md)에 기록돼 있습니다. MTP·KV 최적화까지 포함한 총 2,100건 비교와 실패 분석은 [최종 분석 리포트](reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)에서 확인할 수 있습니다. 재분석 가능한 원시는 [benchmark/results](benchmark/results/)에 함께 보관합니다.
