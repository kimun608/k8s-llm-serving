# 3. 실패한 최적화 기록: FP8 KV cache on Apple M4/ARM64 CPU

## 시도 목적

베이스라인에서 512MiB KV cache가 동시성 20부터 100%에 도달하고 active running이 16에서 제한됐다. BF16 대신 8-bit KV를 사용하면 같은 byte 예산에서 더 많은 token block을 저장해 waiting과 preemption을 줄일 수 있다는 가설로 FP8 KV cache를 후보로 선택했다.

## 적용 설정

검증일은 2026-08-28이며 다음 Kustomize candidate overlay를 실제 Kind worker에 배포했다.

- Overlay: `model_serving/k8s/overlays/candidates/kv-fp8`
- Image/runtime: `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0`, vLLM 0.26.0+cpu
- Host/backend: Apple M4 → Docker Desktop Linux/aarch64 → vLLM CPU attention
- 추가 args: `--kv-cache-dtype fp8 --calculate-kv-scales`
- 나머지 조건: baseline과 동일한 512MiB KV, max sequences 20, CPU limit 6, memory limit 6656Mi

```bash
kubectl apply -k model_serving/k8s/overlays/candidates/kv-fp8
kubectl -n llm-serving rollout status deployment/vllm-cpu --timeout=180s
```

## 관찰 결과

새 Pod `vllm-cpu-5cb7864474-n4r4j`는 worker에 정상 스케줄됐지만 Ready가 되지 못했다. 컨테이너는 exit code 1로 종료되어 재시작했고 Kubernetes event에 `BackOff`가 기록됐다. 실패 시점에 기존 baseline Pod는 Deployment의 `Recreate` 전략에 따라 종료된 상태였으므로 Service도 준비되지 않았다.

직접적인 root cause는 CPU attention backend 초기화 중 발생한 다음 예외다.

```text
NotImplementedError: FP8 KV cache on CPU requires x86 with AVX-512 or AMX.
```

따라서 현재 Apple M4/aarch64 CPU에는 vLLM 0.26.0의 FP8 KV attention kernel이 없다. CLI help에 `fp8` 값이 나타나고 config parsing까지 성공했지만, 실제 model layer가 CPU attention implementation을 만들 때 backend 제약 검사가 실행되어 실패했다.

추가로 다음 경고가 발생했다.

```text
Disabling calculate_kv_scales for hybrid model '/models/qwen3.5-0.8b'.
Hybrid models with recurrent layers (GDN, Mamba, SSM) produce unreliable
KV cache scales during the calibration pass ... Using default scale of 1.0 instead.
```

Qwen3.5는 full attention과 recurrent GDN layer가 섞인 hybrid model이다. 설령 지원 hardware에서 기동하더라도 runtime random calibration은 강제로 꺼지며, checkpoint에 검증된 KV scale이 없다면 scale 1.0이 사용된다. 이는 serving 성능뿐 아니라 생성 품질까지 별도 검증해야 함을 의미한다.

## 왜 정식 부하 측정을 하지 않았는가

이 후보는 성능이 낮은 상태로 기동한 것이 아니라 API server 자체가 초기화되지 않았다. 따라서 동일 700건을 보내면 모두 connection failure가 되어 KV quantization 성능을 나타내지 않는다. 정식 before/after 표에서는 실행 가능한 설정만 비교하고, 이 후보는 “현재 장비에서 적용 불가한 최적화”로 별도 기록한다.

## 복구

다음 명령으로 FP8 args가 없는 baseline overlay를 다시 적용했다.

```bash
kubectl apply -k model_serving/k8s/overlays/baseline
kubectl -n llm-serving rollout status deployment/vllm-cpu --timeout=300s
```

복구 Pod `vllm-cpu-879f6998c-k72tr`는 worker에서 Ready 1/1, restart 0으로 기동했다.

## 대체 최적화 결정

8-bit dtype 변경 대신 BF16 KV cache byte 예산을 512MiB에서 768MiB로 늘리고 `max-num-seqs`를 20에서 24로 조정한다. Pod CPU/memory limit과 workload는 유지한다. 이 방식은 정밀도를 바꾸지 않으면서 베이스라인에서 확인된 KV capacity 병목을 직접 완화하고, memory 증가와 active batch/CPU 경쟁이라는 trade-off를 측정할 수 있다.

## 프로덕션 환경에서의 재검토 조건

FP8 KV 자체가 항상 잘못된 최적화라는 결론은 아니다. CUDA 11.8+ 또는 ROCm GPU, 혹은 AVX-512/AMX를 제공하는 지원 x86 CPU에서는 다시 검토할 수 있다. 다만 다음이 선행되어야 한다.

1. target hardware/backend의 FP8 KV kernel 지원 확인
2. 대표 데이터셋으로 calibration한 scale 포함 checkpoint 준비
3. TTFT/TPOT/throughput뿐 아니라 perplexity 또는 task 품질 회귀 측정
4. BF16 대비 실제 KV capacity, dequantization overhead, 비용 비교

공식 vLLM 0.26.0 문서도 FP8 E4M3/E5M2 지원 hardware로 CUDA와 ROCm을 명시한다. 공통 CLI schema만 보고 특정 backend 지원을 판단하지 않고, 실제 server startup과 kernel 경로를 검증해야 한다.

참고: <https://docs.vllm.ai/en/v0.26.0/features/quantization/quantized_kvcache/>
