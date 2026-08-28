# 실행 결과

이 디렉터리는 Task별 실제 실행에서 확인한 메타데이터와 smoke response를 보관한다.

- `build-metadata.txt`: Task 01 이미지 빌드 결과
- `cluster-metadata.txt`: Task 02 Kind 생성 및 이미지 로드 결과
- `deployment-metadata.txt`: Task 03 K8s 배포와 Ready 시간
- `smoke-response.json`: Service API smoke test 결과
- `final-state-metadata.txt`: 모든 실험 후 다시 빌드·로드하고 복구한 `baseline-cpu8` 제출 상태

성능 부하 테스트는 실행기와 함께 관리하기 위해 아래 경로에 보관합니다.

- `../benchmark/results/baseline/raw/`: 동시성별 요청 timing, vLLM metric, Pod cgroup 시계열
- `../benchmark/results/baseline/summary.csv`: 7개 동시성 집계표
- `../benchmark/results/baseline/charts/`: 재생성 가능한 SVG 그래프
- `../benchmark/results/baseline/REPORT.md`: 분석 스크립트가 생성한 리포트
