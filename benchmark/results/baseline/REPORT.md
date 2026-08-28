# CPU vLLM 베이스라인 부하 측정 리포트

## 결론 요약

- 고정된 100개 요청을 동시성 `1, 2, 5, 10, 20, 50, 100`에서 각각 한 번씩 실행하여 총 `700`건을 측정했다.
- nominal 최고 output throughput은 동시성 `100`의 `13.54 token/s`였지만, C=20의 `13.50 token/s`보다 `0.33%` 높은 수준에 불과하다. 실용적 처리량 포화점은 C=20이다.
- 동시성 `1 → 100`에서 E2E p95는 `24.43×`, TTFT p95는 `43.66×`, TPOT p95는 `7.97×`가 됐다.
- C=1→20에서 output throughput은 `2.62×`가 됐지만, C=20→100에서 E2E p95는 추가로 `3.54×` 악화됐다.
- 최초로 scheduler waiting이 관찰된 동시성은 `10`이다. 전체 prefix cache hit 증가량은 `0`, preemption 증가량은 `2`, Pod OOM kill 증가량은 `0`이다.

## 실험 조건

- Host: `Apple M4`, logical CPU `10`, physical memory `16.0GiB`
- Docker Desktop: `10` vCPU, `7.65GiB`, `aarch64`
- Image: `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0`
- Model/API: `qwen3.5-0.8b`, vLLM `0.26.0`
- Request set: source 4종 × 25건, workload file SHA-256 `ce76ecbeb5810392ff94473c13ed98f54d56e3c32c9343bb187ef63f0db2bebc`
- Input tokens: min `105`, mean `297.9`, max `1049`
- Output: 요청당 `64` tokens, `ignore_eos=true`, `temperature=0.0`
- Prefix caching: disabled. 일반 per-request KV cache만 사용
- 각 동시성별 3건 warmup은 통계에서 제외

동시성 C는 100건을 C번 반복한다는 의미가 아니라, 동일한 총 100건 중 최대 C건만 동시에 in-flight가 되도록 하는 closed-loop worker 수다. 따라서 실험당 요청 수는 항상 100건이고 모든 단계의 prompt 순서가 같다.

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.081 | 5.16 | 11.31 / 19.00 | 2.22 / 9.74 | 143.56 / 152.37 | 0 | 7.5% | 5.99 | 5.71GiB |
| 2 | 100.0% | 0.122 | 7.78 | 15.82 / 25.44 | 3.34 / 10.80 | 157.81 / 306.25 | 0 | 13.4% | 5.96 | 5.71GiB |
| 5 | 100.0% | 0.176 | 11.28 | 27.29 / 38.92 | 15.27 / 27.90 | 179.08 / 422.60 | 0 | 32.8% | 5.55 | 5.76GiB |
| 10 | 100.0% | 0.188 | 12.06 | 54.16 / 66.80 | 25.39 / 43.46 | 412.73 / 753.07 | 1 | 64.2% | 5.52 | 5.82GiB |
| 20 | 100.0% | 0.211 | 13.50 | 89.30 / 131.17 | 35.70 / 70.41 | 857.63 / 1040.10 | 11 | 100.0% | 5.46 | 5.83GiB |
| 50 | 100.0% | 0.210 | 13.46 | 216.41 / 254.46 | 168.19 / 204.58 | 818.13 / 1038.46 | 40 | 100.0% | 5.50 | 5.83GiB |
| 100 | 100.0% | 0.212 | 13.54 | 292.90 / 464.06 | 228.07 / 425.21 | 765.29 / 1214.28 | 91 | 100.0% | 5.54 | 5.85GiB |

서버 counter의 prompt/generation token 증가량과 클라이언트 usage 합계는 `summary.csv`에서 교차 확인할 수 있다. 차이가 있으면 scrape 시작/종료 또는 실패 요청을 먼저 점검해야 한다.

## 그래프

- [E2E latency](charts/e2e-latency.svg)
- [TTFT](charts/ttft.svg)
- [TPOT](charts/tpot.svg)
- [Request throughput](charts/request-throughput.svg)
- [Token throughput](charts/token-throughput.svg)
- [Output token throughput](charts/output-token-throughput.svg)
- [Scheduler running/waiting](charts/server-pressure.svg)
- [KV cache](charts/kv-cache.svg)
- [Pod CPU](charts/resources.svg)
- [Pod memory](charts/memory.svg)
- [Source별 prompt tokens](charts/prompt-tokens-by-source.svg)

## 지표 해석

E2E는 사용자가 기다린 전체 시간이다. TTFT는 scheduler 대기와 prefill 영향을 크게 받고, TPOT는 첫 token 이후 decode 진행 속도를 보여준다. 따라서 동시성 증가 시 TTFT와 waiting이 함께 상승하고 TPOT는 상대적으로 덜 변하면 큐 대기가 주원인이다. 반대로 TPOT도 크게 악화되면 동시 batch 간 CPU 연산 경쟁 또는 memory bandwidth 영향을 의심할 수 있다.

Peak KV가 높으면서 waiting/preemption이 발생하면 512MiB KV 예산도 병목에 기여한다. 다만 이 실험에서 KV를 없애는 것은 올바른 비교가 아니다. autoregressive decoding에 필요한 요청 내부 KV는 유지하고, 요청 간 재사용 기능인 Automatic Prefix Caching만 껐다. 실제 결과의 prefix hit 증가량 `0`으로 이 통제를 확인했다.

## 개선·악화 원인 분석

동시성이 1에서 20으로 증가할 때 CPU가 여러 sequence를 batch로 처리하면서 output throughput이 `5.16 → 13.50 token/s`로 개선됐다. 반면 평균 Pod CPU는 모든 단계에서 대체로 6-core limit 근처였으므로, 동시성을 더 높인다고 CPU 계산 자원이 늘어나는 것은 아니다.

C=20에서 peak running은 `16`, waiting은 `11`, KV는 `100%`였다. 512MiB KV가 가득 차면서 configured `max-num-seqs=20`에 도달하기 전에 active running이 16에서 제한됐다. C=50과 100에서는 peak running이 계속 16인 반면 peak waiting만 `40`와 `91`로 증가했다. 그래서 output throughput은 거의 그대로지만 TTFT와 E2E tail이 크게 악화됐다.

C=50/100의 TPOT p50이 C=20보다 약간 낮아진 것은 추가 요청이 decode batch에 무한히 들어간 결과가 아니다. 초과 요청은 first token 전에 queue에서 기다리고, 실제 decode 동시성은 KV capacity가 제한하기 때문이다. 대기 비용은 TPOT보다 TTFT에 주로 나타난다. 전체 preemption `2`회는 KV 100% 구간에서 일부 request state를 재계산했음을 뜻한다.

Peak Pod memory는 최대 `5.85GiB`였고 OOM kill은 `0`회였다. 따라서 높은 latency의 원인은 Pod OOM/restart가 아니라 고정 CPU capacity, KV 포화, scheduler queue로 해석할 수 있다.

## 한계와 다음 비교

이 결과는 로컬 장비에서 설정별 1회 측정한 값이므로 background load와 thermal state 영향을 포함한다. 최종 최적화 비교에서는 동일 100건·동일 64 output tokens를 유지하고 실행 순서를 교차하거나 3회 이상 반복해 중앙값과 변동 폭을 추가하는 것이 좋다.

MTP는 같은 Qwen3.5-0.8B checkpoint에 `speculative_config`만 추가하여 비교해야 한다. MTP는 medium/low QPS의 memory-bound decode에서 유리할 수 있지만, 높은 동시성에서는 draft/verification overhead 때문에 효과가 줄거나 악화될 수 있다. 따라서 output throughput·TPOT뿐 아니라 draft acceptance rate와 CPU 사용량도 함께 판단한다.
