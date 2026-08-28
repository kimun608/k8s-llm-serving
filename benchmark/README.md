# 100-request CPU vLLM baseline benchmark

이 폴더는 배포된 `vllm-cpu` Kubernetes Service에 동일한 100개 요청을 보내고, 동시성 증가에 따른 지연시간·처리량·서버 포화를 재현 가능하게 측정합니다. 모델 정답률을 평가하는 실험이 아니라 **추론 서빙 성능**을 평가하는 실험입니다.

## 실험 질문

1. 동시 요청 수가 `1 → 2 → 5 → 10 → 20 → 50 → 100`으로 늘 때 요청/토큰 처리량은 어디까지 증가하는가?
2. E2E latency, TTFT, TPOT의 p50/p95/p99는 어느 지점부터 악화되는가?
3. 지연 증가가 vLLM 대기열, 실행 중 요청 수, KV cache, CPU 또는 메모리와 함께 나타나는가?
4. 이후 최적화를 적용했을 때 동일한 입력·출력 조건에서 실제 개선이 재현되는가?

## 고정 워크로드

공개 LLM 벤치마크 네 종류에서 고정 시드로 25개씩 선택하여 정확히 100개를 생성합니다.

| 소스 | 건수 | 요청 특성 | 공식 원본 |
|---|---:|---|---|
| GSM8K test | 25 | 수학 추론, 짧은~중간 길이 | `openai/grade-school-math` |
| HumanEval | 25 | Python 코드 완성, 중간 길이 | `openai/human-eval` |
| TruthfulQA | 25 | 사실 기반 질의, 짧은 길이 | `sylinrl/TruthfulQA` |
| LongBench Qasper | 25 | 논문 문맥 기반 QA, 긴 길이 | `THUDM/LongBench` |

선택 시드는 `20260828`입니다. 데이터 준비 결과에는 원본 URL·원본 SHA-256·각 프롬프트 SHA-256을 기록합니다. LongBench 문맥은 로컬 모델의 2,048-token 한도를 넘지 않도록 결정적인 문자 길이로 잘라 사용하며, 실제 prompt token 수는 서버 응답의 usage로 기록합니다. HumanEval 생성 코드는 실행하지 않습니다.

```bash
make benchmark-data
```

생성물:

- `data/prompts.jsonl`: 정확히 100개인 고정 요청 집합
- `data/source-manifest.json`: 원본 버전, SHA-256, 선택 조건
- `data/cache/`: 내려받은 원본(커밋 제외)

## 측정 조건

기본값은 `config/baseline.json`에 고정합니다.

- 모델: native MTP layer를 포함한 `qwen3.5-0.8b`
- API: OpenAI-compatible `/v1/chat/completions`, streaming
- 요청 수: 동시성별 100건, 총 700건
- 동시성: `1, 2, 5, 10, 20, 50, 100`
- 스케줄: closed-loop, 각 단계에서 최대 N건만 in-flight
- 생성 길이: 요청당 정확히 최대 64 tokens (`ignore_eos=true`)
- 디코딩: `temperature=0`, `seed=20260828`
- 워밍업: 동시성별 3건, 통계 제외
- 단계 간 cooldown: 실행·대기 요청이 0이 된 뒤 3초
- 메트릭 수집 주기: 1초

`ignore_eos=true`로 출력 길이 차이가 처리량을 왜곡하지 않게 하고, 모든 동시성에서 프롬프트 순서와 파라미터를 동일하게 유지합니다. 64 tokens는 이후 MTP의 decode 효과를 관찰할 구간을 확보하기 위한 값입니다. C=100은 고정 100건 전체를 한 번에 제출하며, 서버의 `max-num-seqs=20`과 KV 예산을 넘는 요청은 vLLM waiting queue에서 대기합니다. CPU 서빙 시간이 길 수 있으므로 전체 실행은 장비 상태에 따라 한 시간 이상 걸릴 수 있습니다.

### KV cache 통제

일반 KV cache는 각 요청의 autoregressive decoding에서 과거 token을 매번 다시 계산하지 않기 위한 필수 상태이므로 비활성화하지 않습니다. 요청 완료 시 해당 KV block은 회수됩니다. 요청 간 동일 prefix를 재사용하는 Automatic Prefix Caching(APC)은 베이스라인 Deployment에서 `--no-enable-prefix-caching`으로 명시적으로 끕니다. 따라서 동시성 단계 사이에 별도의 cache flush는 필요하지 않으며, 측정 결과에서도 prefix cache hit 증가량이 0인지 확인합니다.

MTP 비교는 같은 Qwen3.5-0.8B checkpoint를 사용해 `MTP off → on`만 변경합니다. 후속 overlay는 Qwen 공식 vLLM recipe의 `{"method":"qwen3_next_mtp","num_speculative_tokens":2}`를 시작점으로 사용합니다. MTP는 cross-request cache가 아니라 native prediction head가 다음 token 후보를 제안하고 target model이 검증하는 speculative decoding입니다.

## 선정 지표

### 1. 사용자 체감 지표(클라이언트에서 측정)

| 지표 | 단위 | 의미 |
|---|---:|---|
| Success rate | % | HTTP/SSE 요청 중 정상 완료 비율 |
| E2E latency | s/request | 요청 전송부터 마지막 스트림 청크까지 |
| TTFT | s/request | 요청 전송부터 첫 content 청크까지 |
| TPOT | ms/token | 첫 토큰 이후 남은 생성 시간 ÷ `(completion_tokens - 1)` |
| Request throughput | request/s | 정상 완료 요청 수 ÷ 단계 실측 시간 |
| Output throughput | token/s | 정상 completion token 합 ÷ 단계 실측 시간 |

평균만으로는 대기열에 의한 일부 느린 요청을 숨길 수 있으므로 latency는 p50·p95·p99를 함께 봅니다. TTFT는 입력 처리와 스케줄러 대기 영향을, TPOT는 첫 토큰 이후 디코딩 속도를 더 잘 분리합니다.

### 2. 원인 분석 지표(vLLM `/metrics`와 Pod cgroup)

| 지표 | 의미 |
|---|---|
| `vllm:num_requests_running` | 엔진에서 실행 중인 요청 수 |
| `vllm:num_requests_waiting` | 스케줄러 대기 요청 수 |
| `vllm:kv_cache_usage_perc` | KV cache 사용률 |
| prompt/generation token counter | 서버가 실제 처리한 token 증가량 |
| preemption counter | KV 부족 등으로 선점된 요청 수 |
| prefix cache query/hit counter | 이후 prefix caching 최적화 효과 확인용 |
| Pod cgroup CPU usage | 컨테이너 전체 프로세스의 평균 CPU core 사용량 |
| Pod cgroup memory current | 컨테이너 전체의 peak memory working value |

vLLM의 `process_*` 메트릭은 API 프로세스 관점일 수 있으므로, 실제 컨테이너 전체 자원량은 Pod 내부 cgroup v2의 `cpu.stat`와 `memory.current`를 함께 수집합니다.

## 베이스라인 실행

사전 조건:

```bash
make verify-cluster
make status
make smoke
```

전체 실험:

```bash
make benchmark-baseline
```

저장소에는 제출용 실측 결과가 이미 들어 있으므로 재실행할 때는 이를 덮어쓰지 않는 새 root를 지정합니다.

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-results.XXXXXX)"
make benchmark-baseline RESULTS_ROOT="$rerun_root"
```

macOS에서는 이 Make target이 자동으로 `caffeinate -dimsu`를 사용합니다. 장시간 측정 중 노트북이 sleep 상태에 들어가면 Docker VM과 client timer가 함께 멈추고 E2E/TTFT 및 1초 metric time series가 왜곡되기 때문입니다. 다른 OS에서는 별도 명령 없이 그대로 실행합니다. 전원 연결을 권장하며, 실행 중 Docker Desktop의 CPU/memory 설정을 변경하지 않습니다.

스크립트를 직접 실행할 수도 있습니다.

```bash
python3 benchmark/scripts/run_benchmark.py \
  --config benchmark/config/baseline.json \
  --prompts benchmark/data/prompts.jsonl \
  --output benchmark/results/baseline \
  --max-new-phases 4

python3 benchmark/scripts/run_benchmark.py \
  --config benchmark/config/baseline.json \
  --prompts benchmark/data/prompts.jsonl \
  --output benchmark/results/baseline \
  --resume

python3 benchmark/scripts/analyze.py \
  --input benchmark/results/baseline
```

기본 실행기는 `kubectl port-forward service/vllm-cpu 18000:8000`을 시작하고 종료 시 정리합니다. 이미 접근 가능한 주소가 있다면 `--base-url http://127.0.0.1:8000`처럼 지정할 수 있습니다.

`make benchmark-*` 정식 target은 장시간 실행이 중단돼 메모리에 있던 phase를 잃지 않도록 처음 4개 phase를 저장하고, 체크섬·Pod 실행 인자·모델 identity를 다시 검증한 뒤 남은 3개 phase를 `--resume`으로 이어서 실행합니다. 임의 중단 뒤에도 `--resume`을 직접 사용하면 성공한 100건과 raw/metric 파일이 모두 존재하는 phase만 건너뜁니다. 불완전한 phase나 다른 배포에는 재개하지 않습니다.

짧은 기능 검증은 전체 700건을 수행하지 않습니다.

```bash
make benchmark-check
```

## 결과 구조

```text
results/baseline/
├── run-manifest.json
├── raw/
│   ├── requests-c01.jsonl
│   ├── server-metrics-c01.csv
│   ├── phase-c01.json
│   └── ...                     # C=1,2,5,10,20,50,100
├── summary.csv
├── summary.json
├── REPORT.md
└── charts/
    ├── e2e-latency.svg
    ├── ttft.svg
    ├── tpot.svg
    ├── output-token-throughput.svg
    ├── server-pressure.svg
    ├── kv-cache.svg
    └── ...
```

원시 요청 결과에는 모델 응답 본문 대신 식별자, token 수, timing, 상태만 저장합니다. 분석 스크립트는 원시 파일에서 표·SVG 그래프·Markdown 리포트를 다시 생성하므로 수작업으로 수치를 옮기지 않습니다.

현재 완료된 실측 결과는 [results/baseline/REPORT.md](results/baseline/REPORT.md), 과제 제출 관점의 분석은 [../reports/02_BASELINE_BENCHMARK.md](../reports/02_BASELINE_BENCHMARK.md)에서 확인할 수 있습니다.

## 최적화 재측정과 비교

baseline을 보존한 채 native MTP와 MTP+KV tuned overlay를 각각 배포해 같은 700건을 실행합니다.

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-results.XXXXXX)"

make deploy
make benchmark-baseline RESULTS_ROOT="$rerun_root"

make deploy-mtp
make smoke
make benchmark-mtp RESULTS_ROOT="$rerun_root"

make deploy-mtp-kv-tuned
make smoke
make benchmark-mtp-kv-tuned RESULTS_ROOT="$rerun_root"

make benchmark-compare RESULTS_ROOT="$rerun_root"
```

`benchmark-compare`는 세 설정의 prompt SHA-256과 고정 config, phase별 100/100 성공, client/server token counter 일치를 먼저 검증합니다. 통과하면 [results/comparison/REPORT.md](results/comparison/REPORT.md), 비교 CSV와 10개 SVG 그래프를 생성합니다. 원인 분석과 적용 실패 후보는 [최종 최적화 리포트](../reports/04_OPTIMIZATION_FINAL_ANALYSIS.md)를 봅니다.

### CPU limit 하나만 바꾸는 A/B

baseline의 container CPU limit만 6에서 8로 변경하는 별도 실험은 다음 순서로 실행합니다.

```bash
make deploy
make benchmark-baseline

make deploy-baseline-cpu8
make smoke
make benchmark-baseline-cpu8

make benchmark-compare-cpu8
```

`benchmark-compare-cpu8`는 workload와 token counter뿐 아니라 rendered container 명세에서 CPU limit 외 필드가 동일한지, 정식 phase의 UTC wall clock과 monotonic timer가 1%/5초 이내로 일치하는지, metric scrape error가 없는지 검증합니다. 실측 표·그래프는 [results/comparison-cpu8/REPORT.md](results/comparison-cpu8/REPORT.md), 원인 분석은 [CPU 8 분석 리포트](../reports/05_BASELINE_CPU8_ANALYSIS.md)에 있습니다.

host sleep이나 실행 중단이 발견된 phase만 원시 자료를 보존한 뒤 다시 실행할 수 있습니다.

```bash
python3 benchmark/scripts/run_benchmark.py \
  --config benchmark/config/baseline-cpu8.json \
  --prompts benchmark/data/prompts.jsonl \
  --output benchmark/results/baseline-cpu8 \
  --resume \
  --rerun-concurrencies 10 \
  --rerun-reason "host suspension detected" \
  --max-new-phases 1
```

교체 전 request JSONL, metric CSV, phase JSON과 제외 사유는 결과 폴더의 `excluded/` 아래에 자동 보존됩니다.

### CPU limit 8 고정 MTP·KV 비교

완료된 `baseline-cpu8`을 기준으로 CPU와 memory를 고정하고 MTP, 이어서 BF16 KV capacity/scheduler 변경을 적용합니다.

```bash
make deploy-mtp-cpu8
make smoke
make benchmark-mtp-cpu8

make deploy-mtp-kv-tuned-cpu8
make smoke
make benchmark-mtp-kv-tuned-cpu8

make benchmark-compare-cpu8-optimizations
```

`benchmark-compare-cpu8-optimizations`는 세 설정의 총 2,100건, workload/token counter/timer/metric scrape와 rendered container 명세를 검증합니다. 실측 표와 그래프는 [results/comparison-cpu8-optimizations/REPORT.md](results/comparison-cpu8-optimizations/REPORT.md), 원인과 권고는 [CPU8 MTP·KV 분석 리포트](../reports/06_CPU8_MTP_KV_ANALYSIS.md)에 있습니다.

## 해석 원칙

- throughput 증가가 멈추고 p95/p99 TTFT와 waiting이 동시에 증가하면 CPU 처리 용량의 포화로 판단합니다.
- TTFT만 크게 늘고 TPOT 변화가 작으면 디코딩 자체보다 큐 대기가 주원인일 가능성이 큽니다.
- TPOT와 CPU 사용량이 함께 악화되면 동시 batch의 연산 경쟁이나 CPU throttling을 확인합니다.
- KV 사용률 또는 preemption이 상승하면 cache 공간과 `max-num-seqs` 설정을 확인합니다.
- 단 한 번의 로컬 측정은 OS background load 영향을 받으므로 최종 최적화 비교에서는 같은 설정을 여러 번 반복하고 중앙값/신뢰구간을 추가하는 것이 바람직합니다.
