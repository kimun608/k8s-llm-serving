# Local CPU vLLM on Kind Kubernetes

GPU 없이 MTP layer가 포함된 Qwen3.5-0.8B를 vLLM CPU 런타임으로 서빙하는 프로젝트입니다. macOS/Apple Silicon과 Windows 10·11/x64의 Docker Desktop Linux container 환경을 지원하며, 최종 제출 실험은 Windows/Ryzen 환경에서 수행했습니다. 이전 실행 결과도 삭제하지 않고 각 결과 폴더에 보존합니다.

```text
project_process/
├── k8s/                         # Kind 클러스터 설치·검증
├── model_serving/               # vLLM 이미지와 K8s 배포 자원
├── benchmark/                   # 100-request 부하 실행기·데이터·성능 원본
├── optimization/                # CPU·MTP·KV·max-seqs 실험 구성
├── reports/
│   ├── final_report.md          # 최종 제출 보고서
│   └── results/                 # 이전 단계별 보고서와 배포 증적
└── Makefile                     # 전체 실행 진입점
```

## 먼저 읽을 문서

1. [Kubernetes 클러스터 설치·이미지 로드](k8s/README.md)
2. [vLLM 모델 이미지 빌드·K8s 배포](model_serving/README.md)
3. [100-request 벤치마크 실행](benchmark/README.md)
4. [CPU·MTP·KV·max-seqs 최적화 재측정](optimization/README.md)
5. [최종 실험 보고서](reports/final_report.md)

실험 단계별 상세 기록과 실행 증적은 [상세 증거 색인](reports/results/README.md)에서 확인합니다.

## Windows PowerShell 빠른 실행

요구 사항은 Windows 10/11 x64, WSL 2 backend로 실행 중인 Docker Desktop Linux containers입니다. Docker에는 최소 8GiB, 권장 12GiB 이상의 메모리와 CPU 8개 이상을 할당합니다. 최초 빌드는 vLLM 베이스와 모델 checkpoint를 내려받으므로 인터넷 연결과 수 GB의 디스크 여유가 필요합니다.

Windows overlay는 x86_64 런타임의 추가 메모리 사용량을 고려해 Pod limit을 8GiB로 설정합니다. macOS용 6.5GiB 실험 manifest와 저장된 Apple M4 결과는 그대로 보존합니다.

Docker Desktop을 먼저 실행한 뒤 프로젝트 루트의 PowerShell에서 다음을 실행합니다. Kind와 Kubernetes `v1.32.11`에 맞는 kubectl은 시스템 영역을 변경하지 않고 `bin/`에 설치됩니다.

```powershell
.\project.ps1 preflight
.\project.ps1 all
.\project.ps1 smoke
```

단계별 실행과 검증은 다음과 같습니다.

```powershell
.\project.ps1 install-kind
.\project.ps1 install-kubectl
.\project.ps1 image
.\project.ps1 cluster
.\project.ps1 load
.\project.ps1 verify-cluster
.\project.ps1 deploy
.\project.ps1 wait
.\project.ps1 status
.\project.ps1 smoke
```

성공 기준은 control-plane과 worker가 모두 `Ready`, vLLM Pod가 worker에서 `Running`/`Ready 1/1`, 두 Kind node에 로컬 이미지가 존재하고 smoke test에서 `/health` HTTP 200과 chat completion이 반환되는 것입니다. 전체 명령은 `.\project.ps1 help`로 확인합니다.

Dockerfile 또는 모델 이미지를 다시 빌드했다면 같은 로컬 tag와 `imagePullPolicy: Never`를 사용하므로 새 이미지를 로드한 뒤 Pod를 재시작합니다.

```powershell
.\project.ps1 image
.\project.ps1 load
.\project.ps1 restart
.\project.ps1 wait
.\project.ps1 smoke
```

클러스터만 제거하고 로컬 모델 이미지를 유지하려면 `.\project.ps1 clean-cluster`를 사용합니다. benchmark와 보고서 검증에는 Python 3이 추가로 필요하며 `.\project.ps1 install-python`으로 사용자 영역에 설치할 수 있습니다.

### Windows 전체 실험

Windows 최종 실험은 CPU8·MTP off·KV 512MiB를 공통 기준으로 둡니다. 먼저 `baseline-cpu8`, `mtp-cpu8`, `baseline-kv768-cpu8`, `baseline-cpu8-fp8`을 각각 700건씩 실행해 MTP2, KV budget과 FP8 KV의 독립 효과를 확인합니다. 고부하에서 개선된 KV768과 FP8 KV만 `baseline-kv768-fp8-cpu8`으로 결합해 700건을 추가합니다. 정식 합계는 3,500건이며 두 FP8 구성의 C20 20-request gate 40건은 별도입니다.

```powershell
$resultsRoot = Join-Path $PWD 'benchmark\results-windows-cpu8-factors-rerun'
$coreVariants = @(
  'baseline-cpu8',
  'mtp-cpu8',
  'baseline-kv768-cpu8',
  'baseline-cpu8-fp8'
)

.\benchmark\scripts\run-windows-suite.ps1 `
  -ResultsRoot $resultsRoot -Variants $coreVariants -ValidateOnly
.\benchmark\scripts\run-windows-suite.ps1 `
  -ResultsRoot $resultsRoot -Variants $coreVariants

# core 비교 보고서에서 C20/50/100 개선 요인을 판정
.\project.ps1 benchmark-compare-windows-cpu8-factors -ResultsRoot $resultsRoot

$comboVariant = @('baseline-kv768-fp8-cpu8')
.\benchmark\scripts\run-windows-suite.ps1 `
  -ResultsRoot $resultsRoot -Variants $comboVariant -ValidateOnly
.\benchmark\scripts\run-windows-suite.ps1 `
  -ResultsRoot $resultsRoot -Variants $comboVariant

.\project.ps1 benchmark-compare-windows-cpu8-factors -ResultsRoot $resultsRoot
```

첫 실행이 만든 core 비교 보고서에서 공통 baseline 대비 C20/50/100 처리량과 tail latency를 확인한 뒤, 개선된 요인만 `$comboVariant`에 넣습니다. 이번 실측에서는 KV cache 768MiB와 FP8 KV cache만 조건을 충족해 결합했고 MTP는 제외했습니다. Suite는 source·runner·Docker·Git fingerprint와 invocation 이력을 보존하고 실행 중 환경이 바뀌면 중단합니다. 정상 종료와 처리된 실패 후에는 Deployment를 `baseline-cpu8`로 복구합니다. 최종 판단은 [최종 실험 보고서](reports/final_report.md)에서 확인합니다.

## master와 worker의 관계

Kind에서 control-plane은 `project-process-control-plane`, worker는 `project-process-worker`라는 별도 노드 컨테이너로 구성됩니다. 애플리케이션 이미지를 master/worker용으로 나누지 않고 동일한 이미지를 두 노드의 containerd에 로드합니다. Deployment의 `nodeSelector`와 Kubernetes 스케줄러가 vLLM Pod를 worker에 배치합니다.

직접 확인하려면 다음 명령을 사용합니다.

```bash
make verify-cluster
make status
```

## 전체 실행 순서

Docker Desktop을 먼저 실행합니다.

아래 `make` 명령은 macOS 진입점입니다. Windows에서는 위의 `project.ps1`을 사용합니다.

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

전체 벤치마크 재현 방법과 `RESULTS_ROOT` 사용법은 [benchmark 실행 문서](benchmark/README.md), 최적화별 배포 순서는 [optimization 문서](optimization/README.md)를 따릅니다. 이전 저장 결과는 아래 `make` 명령으로, 최종 CPU8 factor 결과는 PowerShell 비교기로 다시 검증합니다.

```bash
make benchmark-compare-all
make validate-docs
```

```powershell
$resultsRoot = Join-Path $PWD 'benchmark\results-windows-cpu8-factors-20260830'
.\project.ps1 benchmark-compare-windows-cpu8-factors -ResultsRoot $resultsRoot
```

최종 수치와 판단은 [최종 실험 보고서](reports/final_report.md)에 정리했습니다. 이전 단계별 보고서와 배포 증적은 [상세 증거 색인](reports/results/README.md), 최종 원본은 [CPU8 factor 결과](benchmark/results-windows-cpu8-factors-20260830/)에 보관합니다.
