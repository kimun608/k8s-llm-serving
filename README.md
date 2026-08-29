# Local CPU vLLM on Kind Kubernetes

Apple M4에서 GPU 없이 MTP layer가 포함된 Qwen3.5-0.8B를 vLLM CPU 런타임으로 서빙하는 프로젝트입니다. 클러스터, 모델 서빙, 부하 측정의 책임을 폴더별로 분리했습니다.

```text
project_process/
├── k8s/                         # Kind 클러스터 설치·검증
├── model_serving/               # vLLM 이미지와 K8s 배포 자원
├── benchmark/                   # 100-request 부하 실행기·데이터·성능 원본
├── optimization/                # CPU·MTP·KV·max-seqs 실험 구성
├── reports/
│   ├── final_report.md          # 최종 제출 보고서
│   └── results/                # 단계별 상세 보고서와 배포 증적
└── Makefile                     # 전체 실행 진입점
```

## 먼저 읽을 문서

1. [Kubernetes 클러스터 설치·이미지 로드](k8s/README.md)
2. [vLLM 모델 이미지 빌드·K8s 배포](model_serving/README.md)
3. [100-request 벤치마크 실행](benchmark/README.md)
4. [CPU·MTP·KV·max-seqs 최적화 재측정](optimization/README.md)
5. [최종 제출 보고서](reports/final_report.md)

실험 단계별 상세 기록과 실행 증적은 [상세 증거 색인](reports/results/README.md)에서 확인합니다.

## master와 worker의 관계

Kind에서 control-plane은 `project-process-control-plane`, worker는 `project-process-worker`라는 별도 노드 컨테이너로 구성됩니다. 애플리케이션 이미지를 master/worker용으로 나누지 않고 동일한 이미지를 두 노드의 containerd에 로드합니다. Deployment의 `nodeSelector`와 Kubernetes 스케줄러가 vLLM Pod를 worker에 배치합니다.

직접 확인하려면 다음 명령을 사용합니다.

```bash
make verify-cluster
make status
```

## 전체 실행 순서

Docker Desktop을 먼저 실행합니다.

```bash
make preflight
make install-kind
make image
make cluster
make load
make verify-cluster
make deploy
make wait
make status
make smoke
```

새 환경에서는 `make all`로 smoke test 직전까지 한 번에 실행할 수 있습니다. 현재 클러스터를 제거하려면 `make clean-cluster`를 사용합니다. 이 명령은 로컬 모델 이미지는 제거하지 않습니다.

전체 벤치마크 재현 방법과 `RESULTS_ROOT` 사용법은 [benchmark 실행 문서](benchmark/README.md), 최적화별 배포 순서는 [optimization 문서](optimization/README.md)를 따릅니다. 저장된 결과를 다시 검증하려면 다음을 실행합니다.

```bash
make benchmark-compare-all
make validate-docs
```

수치와 최종 판단은 [최종 보고서](reports/final_report.md)에, 단계별 보고서와 배포 증적은 [상세 증거 색인](reports/results/README.md)에 정리했습니다. 재생성 가능한 summary·raw metric·그래프는 [benchmark/results](benchmark/results/)에 보관합니다.
