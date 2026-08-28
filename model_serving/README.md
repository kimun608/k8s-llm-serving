# vLLM CPU 모델 이미지 빌드와 Kubernetes 배포

이 폴더는 native MTP layer가 포함된 Qwen3.5 모델을 포함한 vLLM 이미지와 애플리케이션 배포 리소스를 함께 관리합니다.

## 폴더 구조

```text
model_serving/
├── README.md
├── Dockerfile
├── .dockerignore
├── k8s/
│   ├── base/
│   │   ├── namespace.yaml
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── kustomization.yaml
│   └── overlays/
│       ├── baseline/kustomization.yaml
│       ├── mtp/kustomization.yaml
│       ├── mtp-kv-tuned/kustomization.yaml
│       └── candidates/              # 지원 여부 사전 검증용
└── scripts/
    ├── preflight.sh
    ├── status.sh
    └── smoke-test.sh
```

Kind 설치와 노드 구성은 `../k8s/README.md`를 따릅니다.

## 모델과 런타임

| 항목 | 값 |
|---|---|
| Runtime | vLLM `0.26.0+cpu` |
| Base image | `vllm/vllm-openai-cpu:v0.26.0-arm64` |
| Base digest | `sha256:5966fcc14fe241ee7f2dc3d3fd5610ed12968eb9c0d096e1089802b79681efc4` |
| Model | `Qwen/Qwen3.5-0.8B` |
| Model revision | `2fc06364715b967f1860aea9cf38778875588b17` |
| Local image | `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0` |
| Dtype | BF16 |
| Context limit | 2,048 tokens |
| CPU KV cache | 512MiB (`536870912` bytes) |
| Multimodal path | `--language-model-only` |
| Baseline MTP | off (`speculative_config=None`) |

Qwen3.5-0.8B는 0.8B 규모, 약 1.63GiB BF16 checkpoint이며 checkpoint 자체에 native MTP layer가 있습니다. 따라서 베이스라인과 MTP 최적화 실험에서 target model을 바꾸지 않고 speculative decoding 설정만 변경할 수 있습니다. 공식 checkpoint는 멀티모달 구조이지만 과제 요청은 텍스트뿐이므로 vision 입력 경로를 끕니다. Docker VM 약 7.65GiB 안에서 실행하기 위해 Pod limit은 6.5GiB, KV cache는 512MiB로 제한했습니다. 모델을 이미지에 포함해 Pod 시작 시 외부 다운로드가 발생하지 않도록 했습니다.

현재 베이스라인에는 speculative config를 넣지 않습니다. 후속 MTP overlay에서는 Qwen 공식 vLLM recipe와 동일하게 `--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'`를 추가할 계획입니다. 고정한 vLLM 0.26.0 이미지의 CLI가 `qwen3_next_mtp`를 허용하는 것까지 확인했으며, 실제 MTP 기동·부하 측정은 최적화 단계의 결과로 별도 기록합니다.

## 1. 환경 점검

프로젝트 루트에서 실행합니다.

```bash
make preflight
```

Apple ARM64, Docker Linux/ARM64, Docker 메모리, Docker/kubectl/Kind 버전을 확인합니다.

## 2. 모델 서빙 이미지 빌드

```bash
make image
```

직접 실행할 경우 build context는 반드시 `model_serving/`입니다.

```bash
docker build \
  --platform linux/arm64 \
  --progress plain \
  --tag local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0 \
  model_serving
```

Dockerfile은 다음을 수행합니다.

1. vLLM ARM64 CPU 이미지를 digest로 고정한다.
2. Qwen 모델을 고정 commit으로 `/models/qwen3.5-0.8b`에 저장한다.
3. Hugging Face와 Transformers offline mode를 설정한다.
4. OpenAI-compatible API server 기본 인자를 정의한다.

빌드 확인:

```bash
docker image inspect local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0
docker run --rm --entrypoint sh \
  local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0 \
  -c 'vllm --version && test -s /models/qwen3.5-0.8b/model.safetensors.index.json'
```

## 3. Kind에 이미지 로드

`k8s/README.md`에 따라 클러스터를 생성한 다음 실행합니다.

```bash
make load
make verify-cluster
```

이미지 이름에 master/worker를 넣지 않습니다. 동일 이미지를 각 노드에 로드하고 Deployment가 worker를 선택합니다.

## 4. Kubernetes YAML 사전 검증

```bash
kubectl kustomize model_serving/k8s/overlays/baseline
kubectl apply --dry-run=client --validate=false \
  -k model_serving/k8s/overlays/baseline
```

## 5. 배포

```bash
make deploy
make wait
make status
```

배포 리소스:

| 리소스 | 구성 |
|---|---|
| Namespace | `llm-serving` |
| Deployment | `vllm-cpu`, replica 1 |
| Service | `vllm-cpu`, ClusterIP port 8000 |
| Node selection | Linux/ARM64 + worker role |
| CPU request/limit | 4/6 cores |
| Memory request/limit | 4Gi/6.5Gi |
| Probes | `/health` startup/readiness/liveness |
| Image policy | `Never`, Kind에 로드된 이미지 전용 |

Deployment의 nodeSelector가 worker role을 요구하므로 Pod는 control-plane이 아니라 `project-process-worker`에서 실행됩니다.

## 6. 실제 추론 검증

```bash
make smoke
```

Smoke test는 ClusterIP Service를 로컬 port 18000에 임시 포트포워딩해 다음을 확인합니다.

1. `GET /health` → HTTP 200
2. `GET /v1/models` → `qwen3.5-0.8b`
3. `POST /v1/chat/completions` → 실제 CPU 생성 응답

상시 접근이 필요하면:

```bash
kubectl -n llm-serving port-forward service/vllm-cpu 8000:8000
```

## 성공 기준과 실제 결과

| 항목 | 결과 |
|---|---|
| 최초 이미지 빌드 | 76.23초 |
| 이미지 크기 | 2.24GB, Linux/ARM64 |
| vLLM | `0.26.0+cpu` 확인 |
| Pod 위치 | `project-process-worker` |
| Pod create-to-Ready | 약 56초 |
| Pod restart | 0 |
| Health | HTTP 200 |
| Model API | Qwen3.5-0.8B, max length 2,048 확인 |
| Chat completion | 16 output tokens 생성 성공 |

실행 데이터는 `../results/`에 보관합니다. 다음 단계에서는 이 Service에 동일한 프롬프트 100건을 동시성 `1, 2, 5, 10, 20, 50, 100`으로 전송합니다.

최적화 overlay의 선정 근거, 고정 조건, 배포 순서는 [`../optimization/README.md`](../optimization/README.md)를 따릅니다. `baseline`은 그대로 보존하고 MTP와 MTP+KV tuned를 별도 overlay로 적용합니다.
