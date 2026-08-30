# 상세 증거 색인

이 디렉터리는 이전 단계별 보고서와 실행 증적을 보존합니다. 제출 결론은 [최종 실험 보고서](../final_report.md), 원시 수치와 자동 검증은 CPU8 factor 결과 root를 기준으로 합니다.

## 최종 제출 기준

| 구분 | 증거 | 역할 |
|---|---|---|
| 최종 보고서 | [final_report.md](../final_report.md) | CPU8 독립 옵션→선별 조합, 정식 3,500건의 최종 판정 |
| 최종 성능 산출물 | [results-windows-cpu8-factors-20260830](../../benchmark/results-windows-cpu8-factors-20260830/) | raw metric, manifest, summary와 5개 factor 구성 |
| 자동 검증 | [comparison-cpu8-factors/REPORT.md](../../benchmark/results-windows-cpu8-factors-20260830/comparison-cpu8-factors/REPORT.md) | 35 phase raw 재집계, 독립 효과·조합·환경·startup 검증 |
| FP8 gates | [FP8-only](../../benchmark/results-windows-cpu8-factors-20260830/validation-gates/baseline-cpu8-fp8-c20/REPORT.md), [KV768+FP8](../../benchmark/results-windows-cpu8-factors-20260830/validation-gates/baseline-kv768-fp8-cpu8-c20/REPORT.md) | 정식 합계와 분리한 C20 40-request 호환성 확인 |
| Startup 증거 | [startup-evidence](../../benchmark/results-windows-cpu8-factors-20260830/startup-evidence/) | 구성별 Pod, describe, dtype·KV capacity 기동 로그 |

## 보존한 이전 기록

| 구분 | 증거 | 역할 |
|---|---|---|
| 선행 Windows 순차 결과 | [comparison-sequential](../../benchmark/results-windows-sequential-20260830/comparison-sequential/REPORT.md) | CPU6→CPU8 선정과 과거 누적 구성 보존 |
| 초기 Windows 이식 결과 | [results-windows-amd64-20260830](../../benchmark/results-windows-amd64-20260830/) | x86_64 기동·초기 설정 검증; 최종 판정에는 사용하지 않음 |
| 컨테이너·클러스터·배포 | [01_CONTAINER_CLUSTER_DEPLOYMENT.md](01_CONTAINER_CLUSTER_DEPLOYMENT.md) | 이미지 빌드, Kind 구성, Service 배포 기록 |
| CPU6 베이스라인 | [02_BASELINE_BENCHMARK.md](02_BASELINE_BENCHMARK.md) | 최초 700건 측정과 포화 구간 분석 |
| FP8 KV 실패 | [03_FAILED_OPTIMIZATION_FP8_KV.md](03_FAILED_OPTIMIZATION_FP8_KV.md) | ARM64 CPU에서 적용할 수 없었던 설정과 원인 |
| CPU6 최적화 | [04_OPTIMIZATION_FINAL_ANALYSIS.md](04_OPTIMIZATION_FINAL_ANALYSIS.md) | MTP와 capacity bundle의 초기 before/after |
| CPU limit 분리 | [05_BASELINE_CPU8_ANALYSIS.md](05_BASELINE_CPU8_ANALYSIS.md) | CPU limit 6→8 단일 변수 비교 |
| CPU8 최적화 | [06_CPU8_MTP_KV_ANALYSIS.md](06_CPU8_MTP_KV_ANALYSIS.md) | CPU8에서 MTP와 capacity bundle 비교 |
| Apple 전체 감사 기록 | [07_FINAL_COMPREHENSIVE_ANALYSIS.md](07_FINAL_COMPREHENSIVE_ANALYSIS.md) | Apple 8개 설정의 전체 수치와 교차 검증 |
| 배포 증적 | [deployment/](deployment/) | 빌드·클러스터·Pod·smoke metadata |
| 이전 Apple 성능 산출물 | [benchmark/results](../../benchmark/results/) | Apple/ARM64 실행의 raw metric, summary, CSV, SVG |

실험을 다시 실행하는 방법은 [benchmark README](../../benchmark/README.md)를 따릅니다. 최종 판정은 CPU8 독립 옵션→선별 조합 행렬을 기준으로 합니다.
