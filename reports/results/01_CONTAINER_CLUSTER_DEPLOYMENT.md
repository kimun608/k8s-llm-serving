# 1. 컨테이너화, 클러스터 구성 및 K8s 배포

## 실험 환경

- 장비: Apple M4 MacBook Air, 10 CPU cores, 16GB unified memory
- Docker Desktop VM: Linux/ARM64, 10 vCPU, 7.65GiB RAM
- Docker Engine: 28.0.4
- Kind: v0.32.0, Kubernetes v1.32.11
- kubectl: v1.32.2
- GPU·Metal·클라우드 가속: 사용하지 않음

Docker Desktop에 할당된 메모리가 물리 메모리보다 작기 때문에 control-plane 1개와 worker 1개로 구성했다. vLLM Pod는 worker에만 배치한다.

## 모델과 런타임 선택 근거

최종 모델은 `Qwen/Qwen3.5-0.8B` revision `2fc06364715b967f1860aea9cf38778875588b17`이다.

| 기준 | 선택 근거 |
|---|---|
| CPU 실행 가능성 | 0.8B, BF16 checkpoint 1.63GiB로 Docker VM 7.65GiB에서 실행 가능한 범위 |
| 오픈웨이트 | 공식 Qwen repository, Apache-2.0 |
| 과제의 최적화 목표 | checkpoint에 native MTP layer 1개가 있어 target model을 바꾸지 않고 MTP off/on 비교 가능 |
| 로컬 재현성 | 모델 revision과 vLLM base image digest를 고정하고 모델을 이미지에 포함 |
| 텍스트 과제 | `--language-model-only`로 vision 입력 경로를 비활성화 |

처음 검토한 Qwen2.5-0.5B는 더 작지만 native MTP head가 없어 이후 MTP 최적화 비교가 불가능하다. 따라서 베이스라인 측정 전에 Qwen3.5-0.8B로 교체했다. MTP는 단순 런타임 플래그만으로 임의 모델에 추가되는 기능이 아니라 모델 checkpoint가 예측 head를 포함해야 한다.

vLLM `0.26.0+cpu`의 local `CPUModelRunner`에는 speculative decoding의 CPU C++ fallback 구현이 포함돼 있고, 고정 이미지의 CLI가 Qwen 공식 recipe에 쓰이는 `qwen3_next_mtp` method를 허용하는 것을 확인했다. 베이스라인 로그에는 `speculative_config=None`이 기록된다. 이후 최적화판은 같은 checkpoint에 `{"method":"qwen3_next_mtp","num_speculative_tokens":2}`를 추가한다.

참고 문서:

- <https://docs.vllm.ai/en/latest/getting_started/installation/cpu/>
- <https://docs.vllm.ai/en/stable/features/speculative_decoding/>
- <https://huggingface.co/Qwen/Qwen3.5-0.8B>
- <https://kind.sigs.k8s.io/docs/user/quick-start/>

## 컨테이너 이미지

`model_serving/Dockerfile`은 다음 작업을 수행한다.

1. 공식 vLLM ARM64 CPU image `v0.26.0`을 digest로 고정한다.
2. Qwen3.5-0.8B의 고정 revision을 `/models/qwen3.5-0.8b`에 저장한다.
3. Hugging Face/Transformers offline mode를 설정한다.
4. BF16, 2,048-token context, 최대 20 sequences를 기본 인자로 정의한다.
5. Automatic Prefix Caching을 명시적으로 끈다.

```bash
make image
```

실측 결과:

| 항목 | 값 |
|---|---|
| Build duration | 76.23초 |
| Image | `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0` |
| Image size | 2,240,615,803 bytes, 약 2.24GB |
| Image ID | `sha256:5fb6bc4da6f…` |
| Architecture | Linux/ARM64 |
| vLLM | `0.26.0+cpu` |
| Model directory | 약 1.7GB |

모델을 이미지에 포함했기 때문에 Pod 시작 시간에 네트워크 다운로드가 섞이지 않는다.

## Kind 클러스터와 이미지 로드

```bash
make install-kind
make cluster
make load
make verify-cluster
```

master와 worker는 이미지 이름이 아니라 Kubernetes node role이다. 동일한 애플리케이션 이미지를 두 Kind node의 containerd에 import하고, Deployment의 worker `nodeSelector`가 실제 실행 위치를 결정한다.

| 항목 | 결과 |
|---|---|
| Cluster creation | 39.71초 |
| Qwen3.5 image load | 46.61초 |
| control-plane | Ready, `172.18.0.3` |
| worker | Ready, `172.18.0.2` |
| 양쪽 node image config ID | `53e0d7d41094…` |

`imagePullPolicy: Never`이므로 Kind에 image가 없으면 외부 registry에서 다른 image를 가져오는 대신 배포가 명확히 실패한다.

## Kubernetes 리소스

- Namespace: `llm-serving`
- Deployment: `vllm-cpu`, replica 1, `Recreate`
- Service: `vllm-cpu`, ClusterIP `10.96.224.74`, port 8000
- worker nodeSelector: Linux/ARM64 + worker role
- CPU request/limit: 4/6 cores
- Memory request/limit: 4Gi/6656Mi
- KV cache: 512MiB, 19,894 tokens
- Context/max sequences/max batched tokens: 2,048/20/2,048
- startup/readiness/liveness probe: `/health`
- `/dev/shm`: 512Mi memory-backed `emptyDir`

```bash
make deploy
make wait
make status
make smoke
```

최종 Pod는 `project-process-worker`에서 55초 만에 Ready가 됐고 restart 0이다. `/health` 200, `/v1/models`의 `qwen3.5-0.8b`, 실제 chat completion `CPU serving is ready`를 확인했다.

## KV cache와 공정한 베이스라인

일반 KV cache는 한 요청에서 이미 처리한 token의 K/V를 다시 계산하지 않게 하는 autoregressive decoding의 필수 상태다. 이를 제거하면 정상적인 vLLM 서빙과 다른 연산을 측정하게 된다. 요청이 완료되면 해당 KV block은 allocator로 회수된다.

서로 다른 요청 사이에서 동일 prefix block을 재사용하는 기능은 Automatic Prefix Caching(APC)이다. 베이스라인에는 `--no-enable-prefix-caching`을 사용한다. 따라서 동일 100 prompts를 다음 동시성 단계에서 다시 보내도 이전 단계의 prompt KV가 hit되지 않는다. 부하 결과에서 `prefix_cache_hits_total` 증가량 0을 다시 검증한다.

초기 1GiB KV 설정에서는 idle memory가 6GiB limit에 거의 도달했다. Qwen3.5의 모델·컴파일 메모리를 고려해 KV를 512MiB로 줄이고 Pod limit을 6.5GiB로 조정했다. 동시성 20, 20-request 사전 검증에서 다음을 확인했다.

| 지표 | 결과 |
|---|---:|
| 성공 | 20/20 |
| Duration | 95.87초 |
| Peak KV | 98.51% |
| Peak waiting | 12 |
| Peak Pod memory | 5.94GiB |
| Restart/OOM kill | 0/0 |

Peak KV가 높기 때문에 정식 결과에서 waiting과 preemption을 반드시 함께 해석한다. 이 값은 나중에 KV 크기를 바꾸는 최적화 실험의 근거도 된다.

## 구성 중 발견한 문제

1. Kind worker role label을 cluster config에 명시해 Deployment nodeSelector와 맞췄다.
2. Service가 `VLLM_CPU_SERVICE_HOST` 같은 변수를 주입하지 않도록 `enableServiceLinks: false`를 설정했다.
3. 모델 교체 때 base Deployment는 Qwen3.5였지만 Kustomize overlay가 구 Qwen2.5 tag를 덮어쓰는 불일치를 실제 렌더링 검사로 발견해 수정했다.
4. Qwen3.5의 multimodal 경로는 text-only 부하에 불필요하므로 `--language-model-only`로 비활성화했다.
5. 1GiB KV 선할당은 로컬 memory headroom이 부족해 512MiB로 조정했다.

다음 단계의 고정 100-request 부하와 지표 정의는 `benchmark/README.md`에 기록한다.
