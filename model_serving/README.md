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
│       ├── baseline-cpu8/kustomization.yaml
│       ├── mtp/kustomization.yaml
│       ├── mtp-cpu8/kustomization.yaml
│       ├── mtp-kv-tuned/kustomization.yaml       # legacy ID: capacity bundle
│       ├── mtp-kv-tuned-cpu8/kustomization.yaml  # legacy ID: CPU8 capacity bundle
│       ├── mtp-kv768-cpu8/kustomization.yaml     # CPU8 KV-only 2×2 cell
│       ├── mtp-seq24-cpu8/kustomization.yaml     # CPU8 maxseq-only 2×2 cell
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
| CPU KV cache | baseline/MTP/maxseq-only 512MiB (`536870912` bytes); KV-only/capacity bundle 768MiB (`805306368` bytes) |
| Multimodal path | `--language-model-only` |
| Baseline MTP | off (`speculative_config=None`) |

Qwen3.5-0.8B는 0.8B 규모, 약 1.63GiB BF16 checkpoint이며 checkpoint 자체에 native MTP layer가 있습니다. 따라서 베이스라인과 MTP 최적화 실험에서 target model을 바꾸지 않고 speculative decoding 설정만 변경할 수 있습니다. 공식 checkpoint는 멀티모달 구조이지만 과제 요청은 텍스트뿐이므로 vision 입력 경로를 끕니다. Docker VM 약 7.65GiB 안에서 실행하기 위해 Pod limit은 6.5GiB, KV cache는 512MiB로 제한했습니다. 모델을 이미지에 포함해 Pod 시작 시 외부 다운로드가 발생하지 않도록 했습니다.

현재 베이스라인에는 speculative config를 넣지 않습니다. MTP overlay는 Qwen 공식 vLLM recipe와 동일하게 `--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'`를 사용합니다. 실제 MTP 기동·부하 측정은 [최적화 분석 리포트](../reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)에 기록했습니다.

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

### CPU limit 8 단일 변경 배포

`baseline-cpu8` overlay는 위 baseline에서 container CPU limit만 `6 → 8`로 교체합니다. 모델, args, CPU request, memory, KV와 scheduler 설정은 바꾸지 않습니다.

```bash
make deploy-baseline-cpu8
make smoke
```

실제 Pod에서 다음 값으로 확인할 수 있습니다.

```bash
kubectl -n llm-serving get deployment vllm-cpu \
  -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl -n llm-serving exec deployment/vllm-cpu -- cat /sys/fs/cgroup/cpu.max
```

예상 CPU limit은 `8`, cgroup 값은 `800000 100000`입니다. 동일 700건 A/B 절차와 결과는 [CPU limit 실험 README](../optimization/cpu8/README.md)와 [분석 리포트](../reports/05_BASELINE_CPU8_ANALYSIS.md)에 있습니다.

### CPU limit 8에서 MTP·capacity bundle 배포

`mtp-cpu8`은 `baseline-cpu8`과 동일한 Pod CPU/memory request·limit에서 Qwen native MTP 2 tokens만 추가합니다. `mtp-kv-tuned-cpu8`은 같은 MTP 설정에서 BF16 KV byte 예산을 `512→768MiB`, `max-num-seqs`를 `20→24`로 동시에 바꾼 capacity bundle입니다. 이름의 `mtp-kv-tuned`는 기존 명령·결과 경로와의 호환성을 위해 유지한 legacy artifact ID이며 KV-only 변경을 뜻하지 않습니다.

```bash
make deploy-mtp-cpu8
make smoke

make deploy-mtp-kv-tuned-cpu8
make smoke
```

두 overlay 모두 CPU limit은 8이고 GPU resource를 요청하지 않습니다. 시작 로그에서 `device_config=cpu`, `speculative_config=...num_spec_tokens=2`를 확인할 수 있습니다. KV 기동 capacity는 MTP와 capacity bundle에서 각각 9,137, 13,705 tokens로 측정됐습니다. bundle은 두 설정 인자를 함께 변경하므로 결과를 KV 또는 `max-num-seqs` 하나의 단독 인과효과로 해석하지 않습니다. 배포·측정 절차는 [CPU8 실험 README](../optimization/cpu8-mtp-kv/README.md), 결과는 [CPU8 분석 리포트](../reports/06_CPU8_MTP_KV_ANALYSIS.md)에 있습니다.

### CPU limit 8에서 KV·max-num-seqs 단일 변수 배포

Legacy bundle의 혼합 변수를 분리하기 위해 다음 overlay를 추가했습니다.

| Overlay | `mtp-cpu8` 대비 유일한 변경 | CPU / memory limit | 기동 KV capacity |
|---|---|---|---:|
| `mtp-kv768-cpu8` | `--kv-cache-memory-bytes 536870912 → 805306368` | 8 / 6656Mi | 13,705 tokens |
| `mtp-seq24-cpu8` | `--max-num-seqs 20 → 24` | 8 / 6656Mi | 9,137 tokens |

```bash
make deploy-mtp-kv768-cpu8
make smoke

make deploy-mtp-seq24-cpu8
make smoke
```

Rendered YAML을 직접 확인하려면 다음 명령을 사용합니다.

```bash
kubectl kustomize model_serving/k8s/overlays/mtp-kv768-cpu8
kubectl kustomize model_serving/k8s/overlays/mtp-seq24-cpu8
```

두 overlay 모두 CPU-only·MTP2·BF16, image, model, Pod resources와 나머지 scheduler args가 `mtp-cpu8`과 같습니다. 각 700건은 모두 성공했습니다. KV-only는 C≥10의 peak running 최대값을 `5→8`, peak waiting 최대값을 3건 줄였지만 C=10·20 output throughput은 `-10.2%`, `-10.4%`였습니다. Maxseq-only는 peak running/peak waiting을 전혀 바꾸지 않았고 C=5∼100 throughput도 `-0.4∼-5.4%`로 개선되지 않아 상한 20이 병목이 아니었음을 확인했습니다.

배포·측정 절차와 전체 표는 [CPU8 2×2 실험](../optimization/cpu8-factorial/README.md), 원본은 [KV-only 결과](../benchmark/results/mtp-kv768-cpu8/REPORT.md), [maxseq-only 결과](../benchmark/results/mtp-seq24-cpu8/REPORT.md), [8개 variant 종합 비교](../benchmark/results/comparison-all/REPORT.md)에 있습니다. `mtp-kv-tuned-cpu8` 이름은 기존 재현 명령과 결과 경로를 위한 legacy ID로 계속 유지합니다.

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

실행 metadata는 `../results/`, 부하 원본은 `../benchmark/results/`에 보관합니다. 이 Service에 동일한 프롬프트 100건을 동시성 `1, 2, 5, 10, 20, 50, 100`으로 보내는 실험을 설정당 700건씩 완료했습니다.

최적화 overlay의 선정 근거와 기존 배포 순서는 [`../optimization/README.md`](../optimization/README.md), 전체 factor는 [실험 매트릭스](../optimization/EXPERIMENT_MATRIX.md)를 따릅니다. `baseline`을 보존하고 MTP, legacy capacity bundle과 KV/maxseq 단일 변수 overlay를 분리했습니다. 실제 overlay·Make target의 `mtp-kv-tuned` 이름은 legacy ID로 유지합니다. CPU8 기존 비교는 [`../optimization/cpu8-mtp-kv/README.md`](../optimization/cpu8-mtp-kv/README.md), 완료된 분리 실험은 [`../optimization/cpu8-factorial/README.md`](../optimization/cpu8-factorial/README.md), 8개 설정 5,600건 검증은 [comparison-all](../benchmark/results/comparison-all/REPORT.md)에 있습니다.
