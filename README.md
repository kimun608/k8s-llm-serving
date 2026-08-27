# Local CPU vLLM on Kind Kubernetes

Apple M4에서 GPU 없이 Qwen2.5-0.5B-Instruct를 vLLM CPU 런타임으로 서빙하는 프로젝트입니다. 클러스터와 모델 서빙의 책임을 두 폴더로 분리했습니다.

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
├── results/                     # 실제 실행 결과
├── reports/                     # 통합 분석 문서
└── Makefile                     # 전체 실행 진입점
```

## 먼저 읽을 문서

1. [Kubernetes 클러스터 설치·이미지 로드](k8s/README.md)
2. [vLLM 모델 이미지 빌드·K8s 배포](model_serving/README.md)

## master와 worker의 관계

Kind에서 master 역할은 `project-process-control-plane`, worker 역할은 `project-process-worker`라는 별도 노드 컨테이너가 담당합니다. 애플리케이션 이미지 이름에 master/worker를 넣는 것이 아니라 동일한 이미지를 각 노드의 containerd에 로드합니다. 이후 Deployment의 nodeSelector와 Kubernetes 스케줄러가 vLLM Pod를 worker에 배치합니다.

현재 검증된 상태:

- control-plane: `Ready`, IP `172.18.0.3`
- worker: `Ready`, IP `172.18.0.2`
- 두 노드 모두 Docker의 `kind` 네트워크에 연결
- 두 노드 모두 `local/vllm-cpu:qwen2.5-0.5b-vllm0.26.0` 보유
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

전체 실행 결과는 [통합 리포트](reports/01_CONTAINER_CLUSTER_DEPLOYMENT.md)와 [results](results/README.md)에 기록돼 있습니다.
