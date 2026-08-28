# CPU8 KV budget × max-num-seqs 분리 실험

이 문서는 기존 `mtp-kv-tuned-cpu8` 결과의 혼합 변수를 분리한 2×2 실험과 실측 결과를 기록한다. 기존 결과 경로와 명령은 재현성을 위해 보존하고, 새 overlay는 한 번에 한 값만 바꾼다.

## 목적

기존 capacity bundle은 MTP2에서 다음 두 값을 동시에 변경했다.

```diff
- --kv-cache-memory-bytes 536870912
+ --kv-cache-memory-bytes 805306368
- --max-num-seqs 20
+ --max-num-seqs 24
```

따라서 기존 `mtp-cpu8 → mtp-kv-tuned-cpu8` 비교만으로 KV budget과 scheduler 상한의 독립 효과를 말할 수 없었다. 두 누락 셀을 추가해 2×2를 완성하고 각 변수의 관측 증분 효과와 상호작용을 비교했다.

| 실험 | KV budget | max-num-seqs | 상태 | 변경 변수 |
|---|---:|---:|---|---|
| `mtp-cpu8` | 512MiB | 20 | 완료 | 기준 |
| `mtp-kv768-cpu8` | 768MiB | 20 | 완료, 700/700 | KV만 변경 |
| `mtp-seq24-cpu8` | 512MiB | 24 | 완료, 700/700 | max sequences만 변경 |
| `mtp-kv-tuned-cpu8` | 768MiB | 24 | 완료 | legacy combined 셀 |

모든 셀은 CPU limit 8, MTP2, 동일 image/model/memory limit, 동일 100 prompts, output 64 tokens와 동시성 `1, 2, 5, 10, 20, 50, 100`을 사용한다.

## 실행

저장소에 보존한 8개 완료 결과만 다시 검증하고 종합 리포트를 생성하려면 다음 명령을 사용한다.

```bash
make benchmark-compare-all
```

두 신규 설정을 새로 측정할 때는 제출용 결과를 덮어쓰지 않도록 별도 root를 지정한다. 각 명령은 동시성 7단계×100건, 총 700건을 실행한다.

```bash
rerun_root="$(mktemp -d /tmp/k8s-llm-results.XXXXXX)"

make deploy-mtp-kv768-cpu8
make smoke
make benchmark-mtp-kv768-cpu8 RESULTS_ROOT="$rerun_root"

make deploy-mtp-seq24-cpu8
make smoke
make benchmark-mtp-seq24-cpu8 RESULTS_ROOT="$rerun_root"
```

`benchmark-compare-all`은 같은 `RESULTS_ROOT` 아래 8개 variant를 모두 요구한다. 따라서 위 임시 root에 신규 두 셀만 재측정한 직후에는 실행할 수 없으며, 전체 비교를 새로 만들려면 나머지 6개도 같은 root에서 재실행해야 한다.

실행 전 Docker Desktop의 CPU·memory 설정과 host background load를 고정한다. 설정 순서를 교차하고 각 셀을 최소 3회 반복해야 C=1·2에서 관찰된 큰 run-to-run 변동과 설정 효과를 분리할 수 있다. 이번 제출 측정은 셀당 1회이므로 작은 차이를 확정적인 개선으로 해석하지 않는다.

## 검증 결과

- 두 신규 셀 모두 `700/700`건 성공, client/server token counter 일치, metric scrape error·OOM kill 0
- 기존 6개 셀까지 포함한 8개 variant는 총 `5,600/5,600`건 성공
- 모든 run은 동일 prompt SHA-256, tokenized input, model, vLLM, workload config와 동시성 순서를 사용
- factor별 container args와 CPU/memory resource가 기대값과 일치함을 종합 비교기가 검증

원시 결과는 [KV-only](../../benchmark/results/mtp-kv768-cpu8/REPORT.md), [maxseq-only](../../benchmark/results/mtp-seq24-cpu8/REPORT.md), 전체 8개 설정 검증과 비교는 [comparison-all](../../benchmark/results/comparison-all/REPORT.md)에 있다.

## 2×2 실측

단위는 output token/s이고 괄호는 같은 CPU8 `mtp-cpu8` 대비 변화율이다.

| C | MTP 기준 512/20 | KV-only 768/20 | maxseq-only 512/24 | legacy combined 768/24 |
|---:|---:|---:|---:|---:|
| 1 | 8.24 | 8.13 (-1.3%) | 8.97 (+8.9%) | 9.33 (+13.3%) |
| 2 | 10.30 | 10.63 (+3.2%) | 12.04 (+16.8%) | 12.10 (+17.4%) |
| 5 | 14.38 | 12.39 (-13.8%) | 14.30 (-0.6%) | 14.35 (-0.3%) |
| 10 | 14.41 | 12.95 (-10.2%) | 14.36 (-0.4%) | 14.83 (+2.9%) |
| 20 | 14.62 | 13.10 (-10.4%) | 14.40 (-1.5%) | 14.75 (+0.9%) |
| 50 | 14.89 | 14.35 (-3.6%) | 14.46 (-2.9%) | 14.33 (-3.7%) |
| 100 | 15.18 | 14.85 (-2.1%) | 14.35 (-5.4%) | 13.66 (-10.0%) |

### KV-only 판정

KV budget `512→768MiB`는 기동 token capacity를 `9,137→13,705`로 늘렸다. C≥10에서 독립 peak running/waiting은 `5/5→8/2`, `5/15→8/12`, `5/45→8/42`, `5/95→8/92`로 바뀌었다. 즉 실행 폭 5→8과 peak waiting 최대값 3 감소는 KV-only 셀에서 관찰됐고, maxseq-only 셀에서는 나타나지 않았다. 단일 실행이므로 이 차이를 반복 전의 확정적 인과 추정량으로 사용하지 않는다.

하지만 더 많은 active request가 같은 8-core quota를 경쟁했을 가능성과 함께 C=10∼100 TPOT p95가 `+70.4∼+93.1%` 악화됐다. Output throughput도 C=10과 C=20에서 각각 `-10.2%`, `-10.4%`였고 C=50·100은 `-3.6%`, `-2.1%`였다. C=5의 `-13.8%`는 peak running/waiting이 기준과 같은 `5/0`인 비병목 구간이므로 KV의 capacity 효과로 설명할 근거가 없으며 반복 실행이 필요한 run variance로 본다. 따라서 KV 증가는 동시 수용량은 높였지만 이 CPU workload의 속도 최적화로는 채택하지 않는다.

### max-num-seqs-only 판정

KV 512MiB를 유지한 채 `max-num-seqs 20→24`만 바꿔도 모든 동시성에서 peak running/waiting이 MTP 기준과 같았다. 실제 peak running은 최대 5라 기존 상한 20에도 훨씬 못 미치므로 scheduler 상한은 active bottleneck이 아니었다. C=5∼100 throughput은 `-0.4∼-5.4%` 범위(C=5 `-0.6%`)로 개선되지 않았다.

C=1·2의 `+8.9%`, `+16.8%`는 peak running/waiting이 각각 `1/0`, `2/0`이고 상한 20과 24가 모두 비병목이다. 따라서 max-num-seqs 효과의 근거가 없으며 단일 로컬 실행의 host background load, JIT·thermal을 포함한 변동으로 보수적으로 분류한다.

### combined 셀과 최종 결론

Legacy `mtp-kv-tuned-cpu8` ID는 KV 768MiB와 maxseq 24를 함께 바꾼 combined 셀로 계속 보존한다. 분리 실험으로 running 5→8의 원인은 KV 증가이고 maxseq 20→24는 이번 workload에서 비병목임을 확인했다. 다만 단독 효과의 합과 combined 결과가 일관되게 더해지지 않아 한 번씩 실행한 2×2만으로 안정적인 상호작용 크기를 추정할 수 없다.

지속적인 C≥10의 보수적 기본값은 `baseline-cpu8`, 저동시성 후보는 `mtp-cpu8`이다. KV-only, maxseq-only와 legacy combined는 모두 범용 속도 최적화로 채택하지 않는다. 전체 실험 현황과 다음 우선순위는 [실험 행렬](../EXPERIMENT_MATRIX.md)을 본다.

## 후속 보류: baseline max-num-seqs 20 vs 50

`max-num-seqs=50`은 이번 정식 측정에서 제외하고 KV capacity를 더 확보한 후속 scheduler sweep으로 보류한다.

| 실험 | MTP | KV budget | max-num-seqs | 목적 |
|---|---|---:|---:|---|
| `baseline-cpu8` | off | 512MiB | 20 | 완료된 기준 |
| 후속 `baseline-seq50-cpu8` | off | 512MiB | 50 | KV 확장 뒤 scheduler 상한만 증가 |

기존 baseline-cpu8의 peak running은 최대 16으로 이미 20보다 작았다. 따라서 같은 KV512MiB에서 상한만 50으로 높여도 더 많은 request를 실행시키지 못한다. 현재 조건의 20→50은 최적화 탐색보다 run-to-run 변동을 한 번 더 측정하는 데 가까우므로 실행하지 않는다. KV를 늘려 실제 running이 20에 도달한 뒤 `8/12/16/20/24/50` sweep으로 평가한다.
