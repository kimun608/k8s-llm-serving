# Kind Kubernetes 클러스터 구성

이 폴더는 모델 구현과 분리된 로컬 Kubernetes 인프라만 관리합니다.

## 폴더 구조

```text
k8s/
├── README.md
├── kind/
│   └── cluster.yaml          # control-plane 1 + worker 1
└── scripts/
    ├── install-kind.sh       # Kind 다운로드와 checksum 검증
    └── verify-cluster.sh     # 노드 join, 네트워크, 이미지 검증
```

모델 Dockerfile과 Deployment/Service YAML은 `../model_serving/`에 있습니다.

## 클러스터 토폴로지

```text
Docker Desktop Linux/ARM64
└── Docker network: kind
    ├── project-process-control-plane (172.18.0.3)
    │   ├── kube-apiserver
    │   ├── scheduler/controller-manager
    │   └── containerd: vLLM image loaded
    └── project-process-worker (172.18.0.2)
        ├── kubelet + kube-proxy + Kind CNI
        ├── containerd: vLLM image loaded
        └── vLLM Pod scheduled here
```

control-plane과 worker는 서로 다른 Docker 컨테이너지만 동일한 `kind` 네트워크에서 Kubernetes 노드로 동작합니다. `kubectl get nodes`에 worker가 `Ready`로 나타나고 worker의 kubelet이 API server에 보고하는 것이 연결 여부의 기준입니다.

## 왜 이미지 이름을 master/worker로 나누지 않는가

`local/vllm-cpu:qwen2.5-0.5b-vllm0.26.0`은 애플리케이션 아티팩트입니다. master와 worker는 이미지 종류가 아니라 Kubernetes 노드 역할입니다.

`kind load docker-image`는 동일 이미지를 각 Kind 노드의 containerd에 import합니다. control-plane에도 이미지를 넣어 두지만 control-plane에는 기본 taint가 있고, vLLM Deployment도 worker nodeSelector를 사용하므로 실제 모델 Pod는 worker에서만 실행됩니다.

## 고정 버전

| 구성 요소 | 값 |
|---|---|
| Kind | `v0.32.0` |
| Kubernetes | `v1.32.11` |
| Node image | `kindest/node:v1.32.11` |
| Node image digest | `sha256:5fc52d52a7b9574015299724bd68f183702956aa4a2116ae75a63cb574b35af8` |
| Cluster name | `project-process` |

## 1. Kind 설치

프로젝트 루트에서 실행합니다.

```bash
make install-kind
```

시스템 디렉터리를 변경하지 않고 `bin/kind`에 Darwin/ARM64 바이너리를 설치하고 공식 SHA-256 checksum을 검증합니다.

## 2. 클러스터 생성

```bash
make cluster
```

직접 실행할 경우:

```bash
bin/kind create cluster \
  --name project-process \
  --image kindest/node:v1.32.11@sha256:5fc52d52a7b9574015299724bd68f183702956aa4a2116ae75a63cb574b35af8 \
  --config k8s/kind/cluster.yaml \
  --wait 180s
```

## 3. 빌드한 모델 이미지 로드

먼저 `model_serving/README.md`에 따라 이미지를 빌드합니다.

```bash
make image
make load
```

동등한 직접 명령:

```bash
bin/kind load docker-image \
  local/vllm-cpu:qwen2.5-0.5b-vllm0.26.0 \
  --name project-process
```

## 4. 연결과 이미지 검증

```bash
make verify-cluster
```

이 명령은 다음을 모두 확인합니다.

1. control-plane과 worker가 Kind 노드 목록에 존재한다.
2. 두 노드가 Kubernetes `Ready` 상태다.
3. 두 노드 컨테이너가 같은 Docker `kind` 네트워크에 있다.
4. 두 노드의 containerd에 vLLM 이미지가 존재한다.

개별 명령으로는 다음처럼 확인할 수 있습니다.

```bash
kubectl get nodes -o wide
docker exec project-process-control-plane crictl images local/vllm-cpu
docker exec project-process-worker crictl images local/vllm-cpu
```

## 성공 기준

- `project-process-control-plane`: `Ready`, role `control-plane`
- `project-process-worker`: `Ready`, role `worker`
- worker에 `node-role.kubernetes.io/worker` 라벨 존재
- 두 노드에 동일한 vLLM image ID 존재
- worker에서 `kindnet`과 `kube-proxy` Pod 실행

## 실제 측정 결과

| 항목 | 결과 |
|---|---|
| Kind 설치 | v0.32.0, checksum 검증 성공 |
| 클러스터 생성 | 39.71초 |
| 이미지 로드 | 42.29초 |
| control-plane | Ready, `172.18.0.3` |
| worker | Ready, `172.18.0.2` |
| 로드 이미지 | 1.64GB, 양쪽 노드에서 확인 |

## 제거

```bash
make clean-cluster
```

Docker에 빌드된 모델 이미지는 유지합니다.
