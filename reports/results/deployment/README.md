# 배포 증적

이 디렉터리는 컨테이너 빌드, Kind 클러스터, Kubernetes 배포와 smoke test에서 수집한 실행 증적을 보관합니다. **성능 부하 테스트 결과 폴더가 아닙니다.**

- `build-metadata.txt`: Task 01 이미지 빌드 결과
- `cluster-metadata.txt`: Task 02 Kind 생성 및 이미지 로드 결과
- `deployment-metadata.txt`: Task 03 K8s 배포와 Ready 시간
- `smoke-response.json`: Service API smoke test 결과
- `final-state-metadata.txt`: 모든 실험 후 다시 빌드·로드하고 복구한 `baseline-cpu8` 제출 상태

이 폴더의 상위 맥락은 [상세 증거 색인](../README.md), 최종 해석은 [최종 보고서](../../final_report.md)에서 확인합니다. 성능 부하 테스트는 실행기와 함께 [benchmark/results](../../../benchmark/results/)에 보관합니다.
