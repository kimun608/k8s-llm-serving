# CPU 서빙 최적화 실험 매트릭스

이 문서는 완료된 CPU6/CPU8 실험, KV·scheduler 2×2 분리 실험과 다음 단일 변수 후보를 구분한다. 특히 기존 이름 `mtp-kv-tuned*`는 호환성을 위해 유지하지만, 실제로는 KV cache와 scheduler를 동시에 변경한 **legacy capacity bundle**이다. 따라서 이를 KV-only 최적화 결과로 해석하지 않는다.

## 공통 고정 조건

- vLLM `0.26.0+cpu`, Linux `arm64`, Qwen3.5-0.8B BF16, GPU resource 없음
- `--language-model-only`, `--max-model-len 2048`, `--max-num-batched-tokens 2048`
- APC off, 동일한 100개 prompt와 output 64 tokens
- concurrency `1, 2, 5, 10, 20, 50, 100`별 100건: 실험 하나당 700건
- 아래 8개 완료 실험은 총 5,600/5,600건 성공

## 완료된 실제 행렬

`output tok/s`는 전체 7개 값 대신 저·중·고동시성을 대표하는 C1/C5/C20/C100을 표시한다. 전체 결과는 각 결과 디렉터리의 `summary.csv`가 원본이다.

| 결과 디렉터리 | CPU limit | MTP | KV bytes | max-num-seqs | C1 | C5 | C20 | C100 | 올바른 분류 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| `baseline` | 6 | off | 512MiB | 20 | 5.16 | 11.28 | 13.50 | 13.54 | CPU6 baseline |
| `mtp` | 6 | MTP2 | 512MiB | 20 | 7.80 | 11.87 | 11.78 | 12.05 | CPU6 MTP-only |
| `mtp-kv-tuned` | 6 | MTP2 | 768MiB | 24 | 7.43 | 11.40 | 11.84 | 12.29 | legacy capacity bundle |
| `baseline-cpu8` | 8 | off | 512MiB | 20 | 6.44 | 13.16 | 16.22 | 15.15 | CPU8 baseline |
| `mtp-cpu8` | 8 | MTP2 | 512MiB | 20 | 8.24 | 14.38 | 14.62 | 15.18 | CPU8 MTP-only |
| `mtp-kv-tuned-cpu8` | 8 | MTP2 | 768MiB | 24 | 9.33 | 14.35 | 14.75 | 13.66 | legacy capacity bundle |
| `mtp-kv768-cpu8` | 8 | MTP2 | 768MiB | 20 | 8.13 | 12.39 | 13.10 | 14.85 | CPU8 KV-only |
| `mtp-seq24-cpu8` | 8 | MTP2 | 512MiB | 24 | 8.97 | 14.30 | 14.40 | 14.35 | CPU8 maxseq-only |

MTP2는 현재 manifest의 deprecated alias `qwen3_next_mtp`와 speculative token 2를 뜻한다. vLLM 0.26.0은 이 alias를 내부적으로 `mtp`로 바꾸며, MTP layer가 하나인 모델에서 speculative token이 1보다 크면 같은 layer forward를 반복해 acceptance가 낮아질 수 있다고 경고한다. 이후 실험은 `{"method":"mtp","num_speculative_tokens":1}`을 별도 후보로 사용한다.

## 인과성 한계

legacy capacity bundle은 다음 두 값을 함께 변경했다.

```text
KV cache:       512MiB -> 768MiB
max-num-seqs:        20 -> 24
```

vLLM CPU 문서에 따르면 KV 공간 증가는 더 많은 동시 요청과 긴 context를 수용하는 capacity 조정이고, `max-num-seqs`는 한 iteration의 sequence batch 상한으로 output-token 성능에 직접 영향을 준다. 그러므로 bundle과 MTP-only의 차이를 KV 효과로 분해할 수 없다.

CPU8에서 bundle은 MTP-only보다 C1 `+13.3%`, C2 `+17.4%`였지만 C1/C2에서는 두 capacity 상한 모두 병목이 아니다. 반대로 C50 `-3.7%`, C100 `-10.0%`였다. 이 패턴은 단일 설정의 인과 효과보다 run-to-run 변동과 큰 active batch의 CPU 경쟁 가능성을 함께 보여준다. 따라서 작은 차이는 반복 측정 없이 개선으로 판정하지 않는다.

## 완료된 2×2 분리 실험

CPU8·MTP2를 고정하고 아래 네 조합을 동일한 workload hash와 run 내부 request 순서로 측정했다. 신규 두 셀은 각각 700/700건 성공했고 기존 6개 결과와 함께 [전체 종합 비교](../benchmark/results/comparison-all/REPORT.md)가 5,600/5,600건, token counter, timer, metric scrape와 factor별 container 명세를 검증했다.

| 실험 | KV bytes | max-num-seqs | 결과 경로 | 판정 |
|---|---:|---:|---|---|
| 기준 `mtp-cpu8` | 512MiB | 20 | [`results/mtp-cpu8`](../benchmark/results/mtp-cpu8/) | 기준 |
| KV-only `mtp-kv768-cpu8` | 768MiB | 20 | [`results/mtp-kv768-cpu8`](../benchmark/results/mtp-kv768-cpu8/) | capacity 증가, 속도 개선 아님 |
| seq-only `mtp-seq24-cpu8` | 512MiB | 24 | [`results/mtp-seq24-cpu8`](../benchmark/results/mtp-seq24-cpu8/) | 비병목 상한, 개선 없음 |
| combined `mtp-kv-tuned-cpu8` | 768MiB | 24 | [`results/mtp-kv-tuned-cpu8`](../benchmark/results/mtp-kv-tuned-cpu8/) | legacy 결합 셀 |

KV-only는 C≥10에서 peak running 최대값을 `5→8`로 늘리고 peak waiting 최대값을 3건 줄였지만 C=10·20 output throughput은 `-10.2%`, `-10.4%`였다. 이는 늘어난 active batch가 같은 CPU quota를 경쟁했을 가능성과 일치한다. Maxseq-only는 모든 동시성에서 peak running/peak waiting이 기준과 같았고 C=5∼100 throughput이 `-0.4∼-5.4%`(C=5 `-0.6%`)였다. peak running이 최대 5라 기존 상한 20도 비병목이었다.

Maxseq-only C=1·2의 `+8.9%`, `+16.8%`는 상한이 작동하지 않는 `1/0`, `2/0` peak run/wait 구간이므로 설정 효과의 근거가 없고 run-to-run 변동으로 보수적으로 분류한다. 분리 결과와 전체 표는 [CPU8 factorial README](cpu8-factorial/README.md)에 있다.

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-results.XXXXXX)"

make deploy-mtp-kv768-cpu8
make smoke
make benchmark-mtp-kv768-cpu8 RESULTS_ROOT="$rerun_root"

make deploy-mtp-seq24-cpu8
make smoke
make benchmark-mtp-seq24-cpu8 RESULTS_ROOT="$rerun_root"

# 저장소에 보존한 8개 완료 결과 검증
make benchmark-compare-all
```

`benchmark-compare-all`은 같은 root의 8개 variant를 모두 요구하므로 신규 두 셀만 있는 임시 root에는 적용하지 않는다. 현재 결과는 셀당 한 번이므로 다음 확증에서는 각 조합을 최소 3회 반복하고 실행 순서를 교차한다. C1/C2와 C5의 비병목 구간에서 큰 변동이 관찰됐으므로 중앙값과 변동 범위를 함께 보고한다.

## 후속 보류: CPU8 scheduler 음성 대조 실험

`baseline-seq50-cpu8`은 CPU8 baseline에서 `--max-num-seqs`만 `20 -> 50`으로 높이는 음성 대조 후보다. 이번 5,600건 정식 행렬에서는 제외하고 KV capacity를 더 확보한 scheduler sweep으로 보류한다.

| 실험 | CPU limit | MTP | KV bytes | max-num-seqs | 요청 수 | 목적 |
|---|---:|---|---:|---:|---:|---|
| `baseline-cpu8` | 8 | off | 512MiB | 20 | 700 | 대조 기준 |
| 후속 `baseline-seq50-cpu8` | 8 | off | 512MiB | 50 | 미실행 | KV 확장 뒤 scheduler 상한 확인 |

기존 CPU8 baseline에서 관측된 peak running request는 최대 16이므로 상한 20도 소진되지 않았다. 같은 KV512MiB에서 이를 50으로 올려도 scheduler가 동시에 실행하는 sequence 수는 늘지 않는다. 따라서 현재는 실행하지 않고, KV를 늘려 실제 running이 20에 도달한 뒤 `8/12/16/20/24/50` sweep으로 평가한다.

## 다음 실험 우선순위

1. **OMP thread/affinity:** CPU8을 고정하고 7 threads, 8 threads, 현재 `auto`를 비교한다. 현재 Pod는 8-core CFS quota지만 10 CPU가 보이고 vLLM auto가 inference thread 9개를 binding하므로 oversubscription 가능성이 있다. `cpu.stat`의 `nr_throttled`와 `throttled_usec` delta도 수집한다.
2. **MTP1:** baseline-cpu8에서 generic `mtp`, speculative token 1만 추가한다. MTP는 저동시성 latency profile과 고동시성 throughput profile을 따로 판정한다.
3. **Chunked prefill budget:** chunked prefill을 명시적으로 고정하고 `max-num-batched-tokens=512/1024/2048`을 비교한다. 작은 값은 TPOT에, 큰 값은 TTFT에 유리할 수 있으므로 throughput만으로 채택하지 않는다.
4. **Scheduler sweep:** MTP2·KV512MiB의 `max-num-seqs=24` 단일 표본은 이미 개선이 없었다. 이를 반복하고 `8/12/16/20`을 추가해 throughput, TTFT, TPOT의 Pareto 지점을 찾는다. KV가 running을 제한하는 현재 조건에서 50은 보류한다.
5. **Weight quantization:** 같은 scheduler에서 Arm 공식 지원 경로인 W8A8, 이후 W4A8을 시험한다. 이는 가장 큰 성능 잠재력이 있지만 checkpoint/정밀도가 달라지므로 GSM8K, HumanEval, TruthfulQA 품질 gate를 함께 둔다. MTP와 처음부터 결합하지 않는다.

## 기능별 주의점

- **APC:** 현재 100개 prompt를 concurrency마다 다시 사용하므로 APC를 켠 채 서버를 재사용하면 뒤 phase가 warm-cache 결과가 된다. 공식 baseline 비교에서는 계속 끄고, 공통 system prompt나 multi-turn용 별도 cold/warm 실험에서만 사용한다. APC는 prefill을 줄이지만 decode 자체는 줄이지 않는다.
- **FP8 KV:** CLI가 값을 파싱하는 것과 ARM CPU kernel 지원은 다르다. 공식 FP8 KV 문서는 CUDA/ROCm 지원을 명시하고 현재 Apple M4/ARM64 배포는 초기화에 실패했으므로 재시도 우선순위에서 제외한다.
- **KV bytes:** preemption, waiting 또는 context capacity가 병목일 때만 늘린다. 여유 cache를 추가하는 것 자체가 연산을 빠르게 하지는 않는다.
- **Compilation/eager:** CPU 기본 경로는 `DYNAMO_TRACE_ONCE + Inductor`이고 CUDA graph는 사용하지 않는다. `--enforce-eager`는 compile을 끄는 기동/디버깅 대조군이지 steady-state 최적화로 가정하지 않는다.
- **oneDNN/allocator:** 현재 v0.26 ARM image에는 oneDNN/OpenMP와 TCMalloc이 이미 포함되어 있다. 별도 교체보다 thread 수와 quantized kernel이 실제로 선택되는지 먼저 검증한다.

## 공식 근거

- [vLLM 0.26 CPU thread, KV, batch-size 튜닝](https://github.com/vllm-project/vllm/blob/v0.26.0/docs/getting_started/installation/cpu.md)
- [vLLM 0.26 MTP alias deprecation](https://github.com/vllm-project/vllm/blob/v0.26.0/vllm/config/speculative.py#L686-L690), [speculative depth 경고](https://github.com/vllm-project/vllm/blob/v0.26.0/vllm/config/speculative.py#L897-L905)
- [vLLM Qwen3.5 recipe: MTP의 저동시성 이점과 고동시성 throughput 비용](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)
- [vLLM chunked prefill 튜닝](https://docs.vllm.ai/en/stable/configuration/optimization/#chunked-prefill)
- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/)
- [vLLM 0.26 Arm quantization 지원표](https://github.com/vllm-project/vllm/blob/v0.26.0/docs/features/quantization/README.md#supported-hardware)
- [vLLM 공식 Arm CPU 최적화 보고서](https://vllm.ai/blog/2026-07-29-optimizing-vllm-on-arm-cpus)
- [vLLM Quantized KV Cache 지원 범위](https://docs.vllm.ai/en/stable/features/quantization/quantized_kvcache/)
- [PyTorch CPU oversubscription 지침](https://docs.pytorch.org/docs/stable/notes/multiprocessing.html)
- [vLLM 0.26 CPU compilation 기본 경로](https://github.com/vllm-project/vllm/blob/v0.26.0/vllm/platforms/cpu.py#L163-L193)
