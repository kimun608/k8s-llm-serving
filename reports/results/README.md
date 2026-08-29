# 상세 증거 색인

이 디렉터리는 [최종 보고서](../final_report.md)의 근거가 된 단계별 보고서와 실행 증적을 보존합니다. 최종 결론은 `final_report.md`를 기준으로 하고, 이곳의 문서는 상세 수치·실패 이력·검증 과정을 확인할 때 사용합니다.

| 구분 | 증거 | 역할 |
|---|---|---|
| 컨테이너·클러스터·배포 | [01_CONTAINER_CLUSTER_DEPLOYMENT.md](01_CONTAINER_CLUSTER_DEPLOYMENT.md) | 이미지 빌드, Kind 구성, Service 배포 기록 |
| CPU6 베이스라인 | [02_BASELINE_BENCHMARK.md](02_BASELINE_BENCHMARK.md) | 최초 700건 측정과 포화 구간 분석 |
| FP8 KV 실패 | [03_FAILED_OPTIMIZATION_FP8_KV.md](03_FAILED_OPTIMIZATION_FP8_KV.md) | ARM64 CPU에서 적용할 수 없었던 설정과 원인 |
| CPU6 최적화 | [04_OPTIMIZATION_FINAL_ANALYSIS.md](04_OPTIMIZATION_FINAL_ANALYSIS.md) | MTP와 capacity bundle의 초기 before/after |
| CPU limit 분리 | [05_BASELINE_CPU8_ANALYSIS.md](05_BASELINE_CPU8_ANALYSIS.md) | CPU limit 6→8 단일 변수 비교 |
| CPU8 최적화 | [06_CPU8_MTP_KV_ANALYSIS.md](06_CPU8_MTP_KV_ANALYSIS.md) | CPU8에서 MTP와 capacity bundle 비교 |
| 전체 감사 기록 | [07_FINAL_COMPREHENSIVE_ANALYSIS.md](07_FINAL_COMPREHENSIVE_ANALYSIS.md) | 8개 설정의 전체 수치와 교차 검증 |
| 배포 증적 | [deployment/](deployment/) | 빌드·클러스터·Pod·smoke metadata |
| 성능 산출물 | [benchmark/results](../../benchmark/results/) | 실행기가 생성한 raw metric, summary, CSV, SVG |

실험을 다시 실행하는 방법은 [benchmark README](../../benchmark/README.md), 배포 설정의 변수 차이는 [optimization 실험 매트릭스](../../optimization/EXPERIMENT_MATRIX.md)를 따릅니다.
