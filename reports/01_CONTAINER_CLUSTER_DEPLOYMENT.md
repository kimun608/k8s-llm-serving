# 1. 컨테이너화, 클러스터 구성 및 K8s 배포

## 실험 환경

- 장비: Apple M4 MacBook Air, 10 CPU cores, 16GB unified memory
- Docker Desktop VM: Linux/ARM64, 10 vCPU, 약 7.65GiB RAM
- Docker Engine: 28.0.4
- kubectl: 1.32.2
- GPU 및 Metal 가속: 사용하지 않음

Docker Desktop VM에 할당된 메모리가 물리 메모리보다 작기 때문에 초기 클러스터는 control-plane 1개와 worker 1개로 구성했다. vLLM Pod는 worker에만 배치하고 5GiB memory limit, 1GiB CPU KV cache, 2,048 token context limit를 사용한다.

## 모델과 런타임 선택 근거

`Qwen/Qwen2.5-0.5B-Instruct`는 0.49B 규모의 Apache-2.0 공개 모델이고 한국어를 포함한 다국어 입력을 지원한다. FP16 가중치는 약 1GB이므로 Docker Desktop, Kind 시스템 컴포넌트와 함께 7.65GiB VM 메모리 안에서 실행할 가능성이 높다.

macOS 네이티브 vLLM Apple Silicon 지원은 실험적이므로, Kubernetes에서 재현 가능한 공식 Linux/ARM64 CPU 이미지 `vllm/vllm-openai-cpu:v0.26.0-arm64`를 사용한다. 이미지 태그뿐 아니라 base image digest, 모델 commit, Kind node image digest를 모두 고정했다.

참고 문서:

- <https://docs.vllm.ai/en/latest/getting_started/installation/cpu/?device=arm>
- <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct>
- <https://kind.sigs.k8s.io/docs/user/quick-start/>

## 컨테이너 이미지

`model_serving/Dockerfile`은 다음 작업을 수행한다.

1. 공식 vLLM ARM64 CPU 이미지를 digest로 고정한다.
2. Qwen 모델의 고정 revision을 `/models/qwen2.5-0.5b-instruct`에 저장한다.
3. Hugging Face와 Transformers offline mode를 설정한다.
4. OpenAI-compatible API server의 기본 실행 인자를 정의한다.

빌드 명령:

```bash
make image
```

모델을 이미지에 포함했기 때문에 최초 빌드에는 수 GB의 네트워크 다운로드와 디스크 공간이 필요하다. 대신 K8s Pod 시작 시 모델 다운로드가 발생하지 않는다.

## Kind 클러스터와 이미지 로드

프로젝트 내부에 고정 버전 Kind 바이너리를 설치하고, Kubernetes v1.32.11 ARM64 node image로 클러스터를 생성한다.

```bash
make install-kind
make cluster
make load
```

클러스터 설치 파일은 `k8s/`에, 모델 이미지와 Deployment/Service 파일은 `model_serving/`에 분리했다. master와 worker는 이미지 이름이 아니라 Kubernetes 노드 역할이다. 동일한 vLLM 이미지를 두 Kind 노드의 containerd에 로드하고, Deployment의 worker nodeSelector가 실제 실행 위치를 결정한다.

로컬 이미지에는 `latest`가 아닌 고정 태그를 사용하고 Deployment의 `imagePullPolicy`는 `Never`로 지정했다. 따라서 Kind에 이미지가 로드되지 않았다면 Pod가 즉시 실패하여 잘못된 외부 pull이나 버전 변화를 숨기지 않는다.

## Kubernetes 리소스

- Namespace: `llm-serving`
- Deployment: `vllm-cpu`, replica 1
- Service: `vllm-cpu`, ClusterIP, port 8000
- worker nodeSelector: Linux/ARM64 Kind worker
- startup/readiness/liveness probe: `/health`
- CPU request/limit: 4/6 cores
- Memory request/limit: 3Gi/5Gi
- `/dev/shm`: 512Mi memory-backed `emptyDir`
- Linux capability: `SYS_NICE`; seccomp: `Unconfined`

배포 및 검증:

```bash
make deploy
make wait
make status
make smoke
```

Smoke test는 Service를 로컬 포트 18000에 임시 포트포워딩한 뒤 `/health`, `/v1/models`, `/v1/chat/completions`를 확인한다.

## 이번 단계에서 기록할 값

실제 실행 후 다음 값을 이 문서와 후속 베이스라인 리포트에 기록한다.

| 항목 | 값 |
|---|---|
| Docker image build duration | 78.30초 |
| Docker image size/ID | 1.64GB / `sha256:7c9bda…f760` |
| Kind cluster creation duration | 39.71초 |
| Image load duration | 42.29초, control-plane과 worker에 로드 |
| Final Pod create-to-Ready | 45초 |
| Smoke test | `/health` 200, model 조회와 chat completion 성공 |

## 실행 중 발견하고 수정한 사항

1. Kind v1.32.11 worker에는 `node-role.kubernetes.io/worker` 라벨이 자동으로 없었다. 설정 파일에 라벨을 명시해 nodeSelector와 일치시켰다.
2. Service 이름 `vllm-cpu`로 인해 Kubernetes가 `VLLM_CPU_SERVICE_HOST` 등의 환경 변수를 Pod에 자동 주입했다. vLLM은 이를 미지원 설정으로 경고하므로 `enableServiceLinks: false`로 비활성화했다. Service DNS와 EndpointSlice 동작에는 영향이 없다.
3. 최초 startup probe는 모델 로딩 중 connection refused를 기록했지만 허용된 startup 기간 안에 정상화됐다. 최종 Pod는 45초 만에 Ready가 됐고 재시작은 없었다.
4. vLLM은 Linux/ARM64 CPU backend, FP16, 1GiB KV cache를 사용했고 최대 2,048-token request 약 42.62개분의 KV cache 용량을 보고했다. 배포 설정의 최대 동시 sequence 20을 수용한다.

100개 프롬프트와 동시성 1, 2, 5, 10, 20의 정식 부하 측정은 다음 단계에서 동일한 배포를 대상으로 수행한다.
