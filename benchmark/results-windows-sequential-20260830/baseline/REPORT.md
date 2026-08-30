# CPU vLLM 베이스라인 부하 측정 리포트

## 결론 요약

- 고정된 100개 요청을 동시성 `1, 2, 5, 10, 20, 50, 100`에서 각각 한 번씩 실행하여 총 `700`건을 측정했다.
- nominal 최고 output throughput은 동시성 `100`의 `83.63 token/s`다. 최고값의 95%에 처음 도달한 실용적 처리량 포화점은 C=`20`이고, 이후 추가 이득은 최대 `2.37%`다.
- 동시성 `1 → 100`에서 E2E p95는 `16.30×`, TTFT p95는 `56.47×`, TPOT p95는 `3.23×`가 됐다.
- C=1→`20`에서 output throughput은 `4.97×`가 됐고, 포화점→C=`100`에서 E2E p95는 `3.40×`가 됐다.
- 최초로 scheduler waiting이 관찰된 동시성은 `20`이다. 전체 prefix cache hit 증가량은 `0`, preemption 증가량은 `2`, Pod OOM kill 증가량은 `0`이다.

## 실험 조건

- Host: `AMD Ryzen 7 7800X3D 8-Core Processor`, logical CPU `16`, physical memory `31.7GiB`
- Docker Desktop: `16` vCPU, `15.45GiB`, `x86_64`
- Image: `local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0`
- Model/API: `qwen3.5-0.8b`, vLLM `0.26.0`
- Request set: source 4종 × 25건, workload file SHA-256 `0a16c94dc0a03f7ba675697df50009fe04ed69407b788c2be99526446f8701fc`
- Input tokens: min `105`, mean `297.9`, max `1049`
- Output: 요청당 `64` tokens, `ignore_eos=true`, `temperature=0.0`
- Prefix caching: disabled. 일반 per-request KV cache만 사용
- 각 동시성별 3건 warmup은 통계에서 제외

동시성 C는 100건을 C번 반복한다는 의미가 아니라, 동일한 총 100건 중 최대 C건만 동시에 in-flight가 되도록 하는 closed-loop worker 수다. 따라서 실험당 요청 수는 항상 100건이고 모든 단계의 prompt 순서가 같다.

## 결과

| C | 성공률 | req/s | output tok/s | E2E p50 / p95 (s) | TTFT p50 / p95 (s) | TPOT p50 / p95 (ms) | peak wait | peak KV | avg CPU | peak RAM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100.0% | 0.257 | 16.44 | 3.74 / 4.68 | 0.33 / 1.27 | 54.01 / 54.82 | 0 | 7.5% | 6.00 | 6.36GiB |
| 2 | 100.0% | 0.447 | 28.63 | 4.38 / 5.09 | 0.49 / 1.53 | 57.68 / 75.69 | 0 | 13.4% | 6.00 | 6.44GiB |
| 5 | 100.0% | 0.829 | 53.03 | 5.72 / 7.18 | 1.77 / 3.22 | 62.15 / 89.80 | 0 | 32.8% | 6.00 | 6.60GiB |
| 10 | 100.0% | 1.163 | 74.44 | 8.72 / 9.59 | 2.78 / 4.63 | 92.21 / 123.39 | 0 | 64.2% | 5.99 | 6.77GiB |
| 20 | 100.0% | 1.277 | 81.70 | 13.84 / 22.44 | 4.02 / 11.50 | 156.47 / 178.76 | 12 | 100.0% | 5.99 | 6.78GiB |
| 50 | 100.0% | 1.288 | 82.42 | 35.34 / 42.05 | 26.10 / 32.49 | 146.43 / 177.80 | 41 | 100.0% | 5.99 | 6.82GiB |
| 100 | 100.0% | 1.307 | 83.63 | 46.39 / 76.30 | 36.92 / 71.86 | 142.82 / 177.00 | 89 | 98.5% | 5.99 | 6.88GiB |

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

Peak KV가 높으면서 waiting/preemption이 발생하면 `512MiB` KV 예산도 병목에 기여할 수 있다. 다만 이 실험에서 KV를 없애는 것은 올바른 비교가 아니다. autoregressive decoding에 필요한 요청 내부 KV는 유지하고, 요청 간 재사용 기능인 Automatic Prefix Caching만 껐다. 실제 결과의 prefix hit 증가량 `0`으로 이 통제를 확인했다.

## 개선·악화 원인 분석

동시성이 1에서 포화점 C=`20`까지 증가할 때 batching으로 output throughput이 `16.44 → 81.70 token/s`로 변했다. 관측된 최대 평균 Pod CPU는 `6.00` cores이고 container CPU limit은 `6` cores이므로, 포화점 이후 동시성 증가는 CPU quota 자체를 늘리지 않는다.

포화점 C=`20`에서 peak running/waiting/KV는 `16/12/100.0%`였다. 설정값은 KV `512MiB`, `max-num-seqs=20`다. C=50과 C=100의 peak running/waiting은 각각 `16/41`, `16/89`였다. 처리량이 거의 늘지 않는데 waiting과 TTFT/E2E가 증가한다면 추가 요청은 service rate를 높이기보다 queue를 키운 것으로 해석한다.

TTFT는 first token 전 queue·prefill 시간을, TPOT는 first token 이후 decode 진행을 주로 반영한다. 따라서 waiting과 TTFT가 함께 증가하고 TPOT 변화가 더 작으면 대기 비용이 중심인 패턴이다. 전체 preemption 증가량은 `2`이며, 0보다 클 때만 KV pressure에 따른 recompute 가능성을 함께 고려한다.

Peak Pod memory는 최대 `6.88GiB`였고 OOM kill은 `0`회였다. 따라서 높은 latency의 원인은 Pod OOM/restart가 아니라 고정 CPU capacity, KV 포화, scheduler queue로 해석할 수 있다.

## 한계와 다음 비교

이 결과는 로컬 장비에서 설정별 1회 측정한 값이므로 background load와 thermal state 영향을 포함한다. 최종 최적화 비교에서는 동일 100건·동일 64 output tokens를 유지하고 실행 순서를 교차하거나 3회 이상 반복해 중앙값과 변동 폭을 추가하는 것이 좋다.

MTP는 같은 Qwen3.5-0.8B checkpoint에 `speculative_config`만 추가하여 비교해야 한다. MTP는 medium/low QPS의 memory-bound decode에서 유리할 수 있지만, 높은 동시성에서는 draft/verification overhead 때문에 효과가 줄거나 악화될 수 있다. 따라서 output throughput·TPOT뿐 아니라 draft acceptance rate와 CPU 사용량도 함께 판단한다.
