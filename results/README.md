# 실행 결과

이 디렉터리는 Task별 실제 실행에서 확인한 메타데이터와 smoke response를 보관한다.

- `build-metadata.txt`: Task 01 이미지 빌드 결과
- `cluster-metadata.txt`: Task 02 Kind 생성 및 이미지 로드 결과
- `deployment-metadata.txt`: Task 03 K8s 배포와 Ready 시간
- `smoke-response.json`: Service API smoke test 결과

성능 부하 테스트의 원본 결과는 후속 작업에서 `results/raw/` 아래에 생성한다.
