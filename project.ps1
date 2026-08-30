[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        'help', 'preflight', 'install-kind', 'install-kubectl', 'install-python', 'image', 'cluster', 'load',
        'verify-cluster', 'deploy', 'restart', 'wait', 'status', 'smoke',
        'benchmark-data', 'benchmark-check', 'benchmark-gate', 'benchmark', 'benchmark-analyze',
        'benchmark-compare', 'benchmark-compare-cpu8',
        'benchmark-compare-cpu8-optimizations', 'benchmark-compare-all',
        'benchmark-compare-windows-sequential', 'benchmark-compare-windows-cpu8-factors',
        'validate-docs', 'all', 'clean-cluster'
    )]
    [string]$Task = 'help',

    [ValidateSet(
        'baseline', 'baseline-cpu8', 'mtp', 'mtp-cpu8', 'mtp-kv-tuned',
        'mtp-kv-tuned-cpu8', 'mtp-kv768-cpu8', 'mtp-seq24-cpu8',
        'mtp-kv768-fp8-cpu8', 'baseline-cpu8-fp8',
        'baseline-kv768-cpu8', 'baseline-kv768-fp8-cpu8'
    )]
    [string]$Variant = 'baseline',

    [string]$ResultsRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$binDirectory = Join-Path $projectRoot 'bin'
$k8sDirectory = Join-Path $projectRoot 'k8s'
$modelServingDirectory = Join-Path $projectRoot 'model_serving'
$benchmarkDirectory = Join-Path $projectRoot 'benchmark'
if (-not $ResultsRoot) {
    $ResultsRoot = Join-Path $benchmarkDirectory 'results'
}

$kindPath = Join-Path $projectRoot 'bin\kind.exe'
$kindVersion = 'v0.32.0'
$kubectlPath = Join-Path $projectRoot 'bin\kubectl.exe'
$kubernetesVersion = 'v1.32.11'
$clusterName = 'project-process'
$kubeconfigPath = Join-Path $binDirectory "$clusterName.kubeconfig"
$kindNodeImage = 'kindest/node:v1.32.11@sha256:5fc52d52a7b9574015299724bd68f183702956aa4a2116ae75a63cb574b35af8'
$imageRepository = 'local/vllm-cpu'
$imageTag = 'qwen3.5-0.8b-vllm0.26.0'
$image = "${imageRepository}:${imageTag}"

# Prefer repository-pinned tools, including from benchmark Python subprocesses.
$originalPath = $env:PATH
$hadOriginalKubeconfig = Test-Path Env:KUBECONFIG
$originalKubeconfig = $env:KUBECONFIG
$env:PATH = "$binDirectory$([IO.Path]::PathSeparator)$env:PATH"

function Invoke-Native {
    param([string]$FilePath, [string[]]$ArgumentList)
    Write-Host "> $FilePath $($ArgumentList -join ' ')" -ForegroundColor DarkGray
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function Test-PythonInvocation {
    param([string]$FilePath, [string[]]$Prefix)
    & $FilePath @($Prefix + @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)')) *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PythonInvocation {
    $pythonCandidates = @(
        (Join-Path $projectRoot 'bin\python\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe')
    )
    foreach ($pythonCandidate in $pythonCandidates) {
        if ((Test-Path -LiteralPath $pythonCandidate) -and (Test-PythonInvocation $pythonCandidate @())) {
            return @{ FilePath = $pythonCandidate; Prefix = @() }
        }
    }

    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        if (Test-PythonInvocation $pyLauncher.Source @('-3')) {
            return @{ FilePath = $pyLauncher.Source; Prefix = @('-3') }
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        if (Test-PythonInvocation $python.Source @()) {
            return @{ FilePath = $python.Source; Prefix = @() }
        }
    }

    throw 'Python 3.10 or newer is required for this task. Install it with: winget install --id Python.Python.3.13 --scope user'
}

function Invoke-Python {
    param([string[]]$ArgumentList)
    $python = Get-PythonInvocation
    Invoke-Native $python.FilePath @($python.Prefix + $ArgumentList)
}

function Assert-KindInstalled {
    if (-not (Test-Path -LiteralPath $kindPath)) {
        throw "Kind is not installed. Run: .\project.ps1 install-kind"
    }
}

function Use-ProjectKubeconfig {
    Assert-KindInstalled
    $clusters = @(& $kindPath get clusters)
    if ($LASTEXITCODE -ne 0 -or $clusters -notcontains $clusterName) {
        throw "Kind cluster $clusterName was not found. Run: .\project.ps1 cluster"
    }
    Invoke-Native $kindPath @(
        'export', 'kubeconfig', '--name', $clusterName, '--kubeconfig', $kubeconfigPath
    )
    $env:KUBECONFIG = $kubeconfigPath
}

function Invoke-ProjectTask {
    param([string]$Name)

    if ($Name -in @('verify-cluster', 'deploy', 'restart', 'wait', 'status', 'smoke', 'benchmark-check', 'benchmark-gate', 'benchmark')) {
        Use-ProjectKubeconfig
    }

    switch ($Name) {
        'help' {
            @'
Windows PowerShell entry point

  .\project.ps1 preflight              Check Docker, kubectl, and host resources
  .\project.ps1 install-kind           Install pinned Kind into .\bin
  .\project.ps1 install-kubectl        Install cluster-compatible kubectl into .\bin
  .\project.ps1 install-python         Install Python 3 for benchmark/report tasks
  .\project.ps1 image                  Build the linux/amd64 vLLM image
  .\project.ps1 cluster                Create the two-node Kind cluster
  .\project.ps1 load                   Load the local image into every Kind node
  .\project.ps1 verify-cluster         Verify nodes, network, and loaded image
  .\project.ps1 deploy                 Deploy the baseline configuration
  .\project.ps1 deploy -Variant mtp    Deploy a named optimization variant
  .\project.ps1 restart                Restart vLLM after a same-tag image update
  .\project.ps1 wait                   Wait for the vLLM Deployment
  .\project.ps1 status                 Show nodes, workload, Service, and events
  .\project.ps1 smoke                  Test health, models, and one completion
  .\project.ps1 all                    Build and deploy through status
  .\project.ps1 clean-cluster          Delete only the project Kind cluster

Benchmark/report tasks require Python 3:

  .\project.ps1 benchmark-data
  .\project.ps1 benchmark-check
  .\project.ps1 benchmark-gate -Variant mtp-kv768-fp8-cpu8 -ResultsRoot C:\temp\results
  .\project.ps1 benchmark -Variant baseline -ResultsRoot C:\temp\results
  .\project.ps1 benchmark-compare-windows-sequential -ResultsRoot C:\temp\results
  .\project.ps1 benchmark-compare-windows-cpu8-factors -ResultsRoot C:\temp\results
  .\project.ps1 benchmark-compare-all -ResultsRoot C:\temp\results
  .\project.ps1 validate-docs
'@ | Write-Host
        }
        'preflight' {
            & (Join-Path $modelServingDirectory 'scripts\preflight.ps1')
        }
        'install-kind' {
            & (Join-Path $k8sDirectory 'scripts\install-kind.ps1') -KindVersion $kindVersion
        }
        'install-kubectl' {
            & (Join-Path $k8sDirectory 'scripts\install-kubectl.ps1') -KubernetesVersion $kubernetesVersion
        }
        'install-python' {
            try {
                $installedPython = Get-PythonInvocation
                $installedVersion = (& $installedPython.FilePath @($installedPython.Prefix + @('--version')) 2>&1 | Out-String).Trim()
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Python is already installed: $installedVersion"
                    return
                }
            } catch {
                # Continue to the installer when no working Python 3 is available.
            }

            $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
            if (-not $winget) {
                throw 'winget is required to install Python automatically.'
            }
            Invoke-Native $winget.Source @(
                'install', '--id', 'Python.Python.3.13', '--exact', '--scope', 'user',
                '--silent', '--accept-package-agreements', '--accept-source-agreements',
                '--source', 'winget'
            )
        }
        'image' {
            Invoke-ProjectTask 'preflight'
            Invoke-Native 'docker' @(
                'build', '--platform', 'linux/amd64', '--provenance=false', '--progress', 'plain',
                '--tag', $image, $modelServingDirectory
            )
            Invoke-Native 'docker' @('image', 'inspect', $image, '--format', 'image={{.RepoTags}} id={{.Id}} size={{.Size}} os={{.Os}} arch={{.Architecture}}')
        }
        'cluster' {
            Invoke-ProjectTask 'install-kind'
            Invoke-ProjectTask 'install-kubectl'
            $clusters = @(& $kindPath get clusters)
            if ($LASTEXITCODE -ne 0) {
                throw 'Unable to list existing Kind clusters.'
            }
            if ($clusters -contains $clusterName) {
                Write-Host "Kind cluster $clusterName already exists; leaving it in place."
            } else {
                Invoke-Native $kindPath @(
                    'create', 'cluster', '--name', $clusterName,
                    '--image', $kindNodeImage,
                    '--config', (Join-Path $k8sDirectory 'kind\cluster.yaml'),
                    '--kubeconfig', $kubeconfigPath,
                    '--wait', '180s'
                )
            }
            Invoke-Native $kindPath @(
                'export', 'kubeconfig', '--name', $clusterName, '--kubeconfig', $kubeconfigPath
            )
            $env:KUBECONFIG = $kubeconfigPath
            # Kubernetes rejects the reserved node-role label when kubelet sets it
            # during bootstrap, so Kind uses a custom scheduling label and the
            # display-only standard role label is applied after the node joins.
            Invoke-Native 'kubectl' @(
                'label', 'node', "$clusterName-worker",
                'llm-serving.local/worker=true', '--overwrite'
            )
            Invoke-Native 'kubectl' @(
                'label', 'node', "$clusterName-worker",
                'node-role.kubernetes.io/worker=', '--overwrite'
            )
        }
        'load' {
            Assert-KindInstalled
            $localImageId = (& docker image inspect $image --format '{{.Id}}' | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or -not $localImageId) {
                throw "Local image $image was not found. Run: .\project.ps1 image"
            }
            $nodes = @(& $kindPath get nodes --name $clusterName)
            if ($LASTEXITCODE -ne 0 -or -not $nodes) {
                throw "Kind cluster $clusterName was not found. Run: .\project.ps1 cluster"
            }
            $nodeImageRef = "docker.io/$image"
            $allNodesCurrent = $true
            foreach ($node in $nodes) {
                $nodeImage = (& docker exec $node ctr -n k8s.io images inspect $nodeImageRef 2>$null | Out-String)
                if ($LASTEXITCODE -ne 0 -or $nodeImage -notmatch [regex]::Escape($localImageId)) {
                    $allNodesCurrent = $false
                    break
                }
            }
            if ($allNodesCurrent) {
                Write-Host "Image $image ($localImageId) is already current on every Kind node."
            } else {
                Invoke-Native $kindPath @('load', 'docker-image', $image, '--name', $clusterName)
            }
        }
        'verify-cluster' {
            & (Join-Path $k8sDirectory 'scripts\verify-cluster.ps1') `
                -ClusterName $clusterName `
                -ImageReference $image `
                -KubernetesVersion $kubernetesVersion `
                -KindNodeImage $kindNodeImage
        }
        'deploy' {
            $overlay = Join-Path $modelServingDirectory "k8s\overlays\windows\$Variant"
            if (-not (Test-Path -LiteralPath $overlay)) {
                throw "Unknown deployment variant: $Variant"
            }
            # A Deployment using imagePullPolicy=Never must never advance its
            # digest annotation until every Kind node has that exact image.
            Invoke-ProjectTask 'load'
            Invoke-Native 'kubectl' @('apply', '-k', $overlay)

            $localImageId = (& docker image inspect $image --format '{{.Id}}' | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or -not $localImageId) {
                throw "Local image $image was not found. Run: .\project.ps1 image"
            }
            $deploymentJson = (& kubectl -n llm-serving get deployment vllm-cpu -o json | Out-String)
            if ($LASTEXITCODE -ne 0) {
                throw 'Unable to inspect the deployed vLLM image annotation.'
            }
            $deploymentObject = $deploymentJson | ConvertFrom-Json
            $annotationsProperty = $deploymentObject.spec.template.metadata.PSObject.Properties['annotations']
            $templateAnnotations = if ($annotationsProperty) { $annotationsProperty.Value } else { $null }
            $deployedImageId = $null
            if ($templateAnnotations) {
                $imageIdProperty = $templateAnnotations.PSObject.Properties['llm-serving.local/image-id']
                if ($imageIdProperty) {
                    $deployedImageId = $imageIdProperty.Value
                }
            }
            if ($deployedImageId -ne $localImageId) {
                Write-Host "Updating Pod template image ID: $localImageId"
                $imageIdPatch = @{
                    spec = @{
                        template = @{
                            metadata = @{
                                annotations = @{ 'llm-serving.local/image-id' = $localImageId }
                            }
                        }
                    }
                } | ConvertTo-Json -Depth 8 -Compress
                Invoke-Native 'kubectl' @(
                    '-n', 'llm-serving', 'patch', 'deployment/vllm-cpu',
                    '--type', 'merge', '--patch', $imageIdPatch
                )
            }
        }
        'restart' {
            Invoke-Native 'kubectl' @('-n', 'llm-serving', 'rollout', 'restart', 'deployment/vllm-cpu')
        }
        'wait' {
            Invoke-Native 'kubectl' @('-n', 'llm-serving', 'rollout', 'status', 'deployment/vllm-cpu', '--timeout=900s')
        }
        'status' {
            & (Join-Path $modelServingDirectory 'scripts\status.ps1')
        }
        'smoke' {
            & (Join-Path $modelServingDirectory 'scripts\smoke-test.ps1')
        }
        'benchmark-data' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\prepare_dataset.py'))
        }
        'benchmark-check' {
            Invoke-ProjectTask 'benchmark-data'
            $checkDirectory = Join-Path ([IO.Path]::GetTempPath()) ("k8s-llm-benchmark-check-" + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $checkDirectory | Out-Null
            Invoke-Python @(
                (Join-Path $benchmarkDirectory 'scripts\run_benchmark.py'),
                '--config', (Join-Path $benchmarkDirectory 'config\baseline.json'),
                '--prompts', (Join-Path $benchmarkDirectory 'data\prompts.jsonl'),
                '--output', $checkDirectory, '--concurrencies', '20', '--limit', '20',
                '--skip-deployment-variant-check'
            )
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\analyze.py'), '--input', $checkDirectory)
            Write-Host "check_output=$checkDirectory"
        }
        'benchmark-gate' {
            Invoke-ProjectTask 'benchmark-data'
            $gateOutput = Join-Path $ResultsRoot "validation-gates\$Variant-c20"
            $gateManifestPath = Join-Path $gateOutput 'run-manifest.json'
            if (Test-Path -LiteralPath $gateManifestPath) {
                $gateManifest = Get-Content -LiteralPath $gateManifestPath -Raw | ConvertFrom-Json
                if ($gateManifest.status -eq 'completed') {
                    Write-Host "Gate for $Variant already completed; regenerating derived report."
                    Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\analyze.py'), '--input', $gateOutput)
                    return
                }
                throw "Gate output is incomplete. Preserve or move it before retrying: $gateOutput"
            }
            if ((Test-Path -LiteralPath $gateOutput) -and @(Get-ChildItem -LiteralPath $gateOutput -Force).Count -gt 0) {
                throw "Gate output is non-empty without a manifest. Preserve or move it: $gateOutput"
            }
            Invoke-Python @(
                (Join-Path $benchmarkDirectory 'scripts\run_benchmark.py'),
                '--config', (Join-Path $benchmarkDirectory "config\$Variant.json"),
                '--prompts', (Join-Path $benchmarkDirectory 'data\prompts.jsonl'),
                '--output', $gateOutput, '--concurrencies', '20', '--limit', '20'
            )
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\analyze.py'), '--input', $gateOutput)
            Write-Host "gate_output=$gateOutput"
        }
        'benchmark' {
            Invoke-ProjectTask 'benchmark-data'
            $variantOutput = Join-Path $ResultsRoot $Variant
            $benchmarkArguments = @(
                (Join-Path $benchmarkDirectory 'scripts\run_benchmark.py'),
                '--config', (Join-Path $benchmarkDirectory "config\$Variant.json"),
                '--prompts', (Join-Path $benchmarkDirectory 'data\prompts.jsonl'),
                '--output', $variantOutput
            )
            $manifestPath = Join-Path $variantOutput 'run-manifest.json'
            if (Test-Path -LiteralPath $manifestPath) {
                $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
                $invalidConcurrencies = @(
                    $manifest.phases | Where-Object {
                        [int]$_.success_count -ne [int]$manifest.prompt_count -or
                        [int]$_.failure_count -ne 0 -or
                        @($_.metrics_scrape_errors).Count -gt 0 -or
                        @($_.runtime_validation_errors).Count -gt 0
                    } | ForEach-Object { [int]$_.concurrency } | Sort-Object -Unique
                )
                $resumeArguments = @($benchmarkArguments + @('--resume'))
                if ($invalidConcurrencies.Count -gt 0) {
                    Write-Host "Preserving and rerunning invalid phase(s): $($invalidConcurrencies -join ', ')"
                    $resumeArguments += @('--rerun-concurrencies')
                    $resumeArguments += @($invalidConcurrencies | ForEach-Object { [string]$_ })
                    $resumeArguments += @(
                        '--rerun-reason',
                        'Automatic Windows suite retry after request, metric, or runtime validation failure'
                    )
                }
                Invoke-Python $resumeArguments
            } else {
                Invoke-Python @($benchmarkArguments + @('--max-new-phases', '4'))
                Invoke-Python @($benchmarkArguments + @('--resume'))
            }
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\analyze.py'), '--input', $variantOutput)
        }
        'benchmark-analyze' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\analyze.py'), '--input', (Join-Path $ResultsRoot $Variant))
        }
        'benchmark-compare' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\compare.py'), '--results-root', $ResultsRoot, '--output', (Join-Path $ResultsRoot 'comparison'))
        }
        'benchmark-compare-cpu8' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\compare_cpu8.py'), '--results-root', $ResultsRoot, '--output', (Join-Path $ResultsRoot 'comparison-cpu8'))
        }
        'benchmark-compare-cpu8-optimizations' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\compare_cpu8_optimizations.py'), '--results-root', $ResultsRoot, '--output', (Join-Path $ResultsRoot 'comparison-cpu8-optimizations'))
        }
        'benchmark-compare-all' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\compare_all_variants.py'), '--results-root', $ResultsRoot, '--output', (Join-Path $ResultsRoot 'comparison-all'))
        }
        'benchmark-compare-windows-sequential' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\compare_windows_sequential.py'), '--results-root', $ResultsRoot, '--output', (Join-Path $ResultsRoot 'comparison-sequential'))
        }
        'benchmark-compare-windows-cpu8-factors' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\compare_windows_cpu8_factors.py'), '--results-root', $ResultsRoot, '--output', (Join-Path $ResultsRoot 'comparison-cpu8-factors'))
        }
        'validate-docs' {
            Invoke-Python @((Join-Path $benchmarkDirectory 'scripts\validate_markdown.py'), '--root', $projectRoot)
        }
        'all' {
            foreach ($step in @('install-kind', 'install-kubectl', 'preflight', 'image', 'cluster', 'load', 'verify-cluster', 'deploy', 'wait', 'status')) {
                Invoke-ProjectTask $step
            }
        }
        'clean-cluster' {
            Assert-KindInstalled
            Invoke-Native $kindPath @('delete', 'cluster', '--name', $clusterName, '--kubeconfig', $kubeconfigPath)
        }
    }
}

try {
    Invoke-ProjectTask $Task
} finally {
    $env:PATH = $originalPath
    if ($hadOriginalKubeconfig) {
        $env:KUBECONFIG = $originalKubeconfig
    } else {
        Remove-Item Env:KUBECONFIG -ErrorAction SilentlyContinue
    }
}
