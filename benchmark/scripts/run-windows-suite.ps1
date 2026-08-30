[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ResultsRoot,

    [ValidateSet(
        'baseline', 'baseline-cpu8', 'mtp-cpu8', 'mtp-kv768-cpu8',
        'mtp-kv768-fp8-cpu8', 'baseline-cpu8-fp8',
        'baseline-kv768-cpu8', 'baseline-kv768-fp8-cpu8'
    )]
    [string[]]$Variants = @(
        'baseline',
        'baseline-cpu8',
        'mtp-cpu8',
        'mtp-kv768-cpu8',
        'mtp-kv768-fp8-cpu8'
    ),

    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$allVariants = @(
    'baseline',
    'baseline-cpu8',
    'mtp-cpu8',
    'mtp-kv768-cpu8',
    'mtp-kv768-fp8-cpu8'
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$projectEntry = Join-Path $projectRoot 'project.ps1'
$appleResultsRoot = (Resolve-Path (Join-Path $projectRoot 'benchmark\results')).Path
$resolvedResultsRoot = if ([IO.Path]::IsPathRooted($ResultsRoot)) {
    [IO.Path]::GetFullPath($ResultsRoot)
} else {
    [IO.Path]::GetFullPath((Join-Path $projectRoot $ResultsRoot))
}
$appleResultsPrefix = $appleResultsRoot.TrimEnd('\') + '\'
if (
    $resolvedResultsRoot.Equals($appleResultsRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $resolvedResultsRoot.StartsWith($appleResultsPrefix, [StringComparison]::OrdinalIgnoreCase)
) {
    throw "Windows results must not overwrite the preserved Apple results under $appleResultsRoot"
}

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)) {
    throw 'This suite runner is only for Windows.'
}

function Get-ExperimentSourceFingerprint {
    $sourceFiles = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $exactFiles = @(
        $projectEntry,
        $PSCommandPath,
        (Join-Path $projectRoot 'model_serving\Dockerfile'),
        (Join-Path $projectRoot 'k8s\kind\cluster.yaml')
    )
    foreach ($path in $exactFiles) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            [void]$sourceFiles.Add([IO.Path]::GetFullPath($path))
        }
    }

    $sourceRoots = @(
        (Join-Path $projectRoot 'benchmark\config'),
        (Join-Path $projectRoot 'benchmark\scripts'),
        (Join-Path $projectRoot 'model_serving\k8s\base'),
        (Join-Path $projectRoot 'model_serving\k8s\components'),
        # Windows wrappers inherit the ordinary overlays, so freeze both the
        # wrappers and every referenced base overlay during a suite run.
        (Join-Path $projectRoot 'model_serving\k8s\overlays'),
        (Join-Path $projectRoot 'model_serving\scripts')
    )
    foreach ($root in $sourceRoots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        Get-ChildItem -LiteralPath $root -File -Recurse |
            Where-Object { $_.Extension -in @('.py', '.ps1', '.yaml', '.yml', '.json') } |
            ForEach-Object { [void]$sourceFiles.Add($_.FullName) }
    }

    $records = foreach ($path in ($sourceFiles | Sort-Object)) {
        $relativePath = $path.Substring($projectRoot.Length).TrimStart('\', '/')
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        "$relativePath|$hash"
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($records -join "`n"))
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace('-', '')
    } finally {
        $sha256.Dispose()
    }
}

New-Item -ItemType Directory -Path $resolvedResultsRoot -Force | Out-Null
$runnerPath = Join-Path $projectRoot 'benchmark\scripts\run_benchmark.py'
$expectedRunnerHash = (Get-FileHash -LiteralPath $runnerPath -Algorithm SHA256).Hash
$expectedSourceFingerprint = Get-ExperimentSourceFingerprint
$expectedDockerFingerprint = (& docker info --format '{{.NCPU}}|{{.MemTotal}}|{{.Architecture}}|{{.ServerVersion}}' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $expectedDockerFingerprint) {
    throw 'Docker Desktop is not ready.'
}
$expectedGitCommit = (& git -C $projectRoot rev-parse HEAD | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $expectedGitCommit) {
    throw 'Unable to capture the Git commit before the experiment.'
}

$existingPortForward = @(
    Get-NetTCPConnection -LocalPort 18000 -State Listen -ErrorAction SilentlyContinue
)
if ($existingPortForward.Count -gt 0) {
    throw 'Local port 18000 is already in use. Stop the stale listener before the suite.'
}

function Invoke-Project {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Task,

        [string]$Variant,

        [string]$CommandResultsRoot
    )

    $parameters = @{ Task = $Task }
    if ($PSBoundParameters.ContainsKey('Variant')) {
        $parameters['Variant'] = $Variant
    }
    if ($PSBoundParameters.ContainsKey('CommandResultsRoot')) {
        $parameters['ResultsRoot'] = $CommandResultsRoot
    }
    & $projectEntry @parameters
    if (-not $?) {
        throw "project.ps1 failed: task=$Task variant=$Variant results=$CommandResultsRoot"
    }
}

function Get-DeployedVariant {
    $kubeconfig = Join-Path $projectRoot 'bin\project-process.kubeconfig'
    $kubectl = Join-Path $projectRoot 'bin\kubectl.exe'
    $value = (& $kubectl --kubeconfig $kubeconfig -n llm-serving get deployment vllm-cpu `
        -o 'jsonpath={.spec.template.metadata.labels.serving-variant}' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $value) {
        throw 'Unable to determine the currently deployed serving variant.'
    }
    return $value
}

function Save-StartupEvidence {
    param([Parameter(Mandatory)][string]$Variant)

    $kubeconfig = Join-Path $projectRoot 'bin\project-process.kubeconfig'
    $kubectl = Join-Path $projectRoot 'bin\kubectl.exe'
    $pod = (& $kubectl --kubeconfig $kubeconfig -n llm-serving get pod `
        -l app.kubernetes.io/name=vllm-cpu `
        -o 'jsonpath={.items[0].metadata.name}' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $pod) {
        throw "Unable to identify the Pod for startup evidence: $Variant"
    }

    $evidenceDirectory = Join-Path $resolvedResultsRoot "startup-evidence\$Variant"
    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    $podJson = (& $kubectl --kubeconfig $kubeconfig -n llm-serving get pod $pod -o json | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to capture Pod JSON for $Variant"
    }
    $startupLog = (& $kubectl --kubeconfig $kubeconfig -n llm-serving logs $pod --timestamps | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to capture startup log for $Variant"
    }
    $description = (& $kubectl --kubeconfig $kubeconfig -n llm-serving describe pod $pod | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to capture Pod description for $Variant"
    }
    [IO.File]::WriteAllText(
        (Join-Path $evidenceDirectory 'pod.json'),
        $podJson,
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $evidenceDirectory 'startup.log'),
        $startupLog,
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $evidenceDirectory 'describe.txt'),
        $description,
        [Text.UTF8Encoding]::new($false)
    )
}

function Assert-FrozenEnvironment {
    $currentRunnerHash = (Get-FileHash -LiteralPath $runnerPath -Algorithm SHA256).Hash
    if ($currentRunnerHash -ne $expectedRunnerHash) {
        throw 'run_benchmark.py changed after the Windows suite started.'
    }
    $currentSourceFingerprint = Get-ExperimentSourceFingerprint
    if ($currentSourceFingerprint -ne $expectedSourceFingerprint) {
        throw 'Benchmark configuration, scripts, or Windows serving manifests changed during the suite.'
    }
    $currentDockerFingerprint = (& docker info --format '{{.NCPU}}|{{.MemTotal}}|{{.Architecture}}|{{.ServerVersion}}' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $currentDockerFingerprint -ne $expectedDockerFingerprint) {
        throw 'Docker CPU, memory, architecture, or engine version changed during the suite.'
    }
    $currentGitCommit = (& git -C $projectRoot rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $currentGitCommit -ne $expectedGitCommit) {
        throw 'Git commit changed during the suite.'
    }
}

function Test-CompleteResultMatrix {
    foreach ($variant in $allVariants) {
        $manifestPath = Join-Path $resolvedResultsRoot "$variant\run-manifest.json"
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            return $false
        }
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        } catch {
            return $false
        }
        if ($manifest.status -ne 'completed') {
            return $false
        }
    }
    return $true
}

function Test-CompleteCpu8FactorScreen {
    foreach ($variant in @(
        'baseline-cpu8',
        'mtp-cpu8',
        'baseline-kv768-cpu8',
        'baseline-cpu8-fp8'
    )) {
        $manifestPath = Join-Path $resolvedResultsRoot "$variant\run-manifest.json"
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            return $false
        }
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        } catch {
            return $false
        }
        if ($manifest.status -ne 'completed') {
            return $false
        }
    }
    return $true
}

function Restore-Baseline {
    Invoke-Project -Task 'deploy' -Variant 'baseline-cpu8'
    Invoke-Project -Task 'wait'
    Invoke-Project -Task 'smoke'
}

if (-not ('WindowsBenchmark.PowerManagement' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace WindowsBenchmark {
    public static class PowerManagement {
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint SetThreadExecutionState(uint executionState);
    }
}
'@
}

$esContinuous = [Convert]::ToUInt32('80000000', 16)
$esSystemRequired = [uint32]0x00000001
$keepAwake = [WindowsBenchmark.PowerManagement]::SetThreadExecutionState(
    $esContinuous -bor $esSystemRequired
)
if ($keepAwake -eq 0) {
    throw 'Windows rejected the keep-awake request.'
}

$startedAt = Get-Date
Write-Host "windows_results_root=$resolvedResultsRoot"
Write-Host "suite_started=$($startedAt.ToString('o'))"
Write-Host "variant_order=$($Variants -join ',')"
Write-Host "source_fingerprint=$expectedSourceFingerprint"

$suiteManifestPath = Join-Path $resolvedResultsRoot 'suite-manifest.json'
$suiteManifest = if ($ValidateOnly) {
    $null
} else {
    $currentInvocation = [ordered]@{
        started_at = $startedAt.ToString('o')
        finished_at = $null
        status = 'running'
        variants = @($Variants)
        comparison_report = $null
    }
    $previousSuiteManifest = if (Test-Path -LiteralPath $suiteManifestPath -PathType Leaf) {
        Get-Content -LiteralPath $suiteManifestPath -Raw | ConvertFrom-Json
    } else {
        $null
    }
    if ($previousSuiteManifest) {
        if (
            [int]$previousSuiteManifest.schema_version -ne 1 -or
            $previousSuiteManifest.source_fingerprint -ne $expectedSourceFingerprint -or
            $previousSuiteManifest.benchmark_runner_sha256 -ne $expectedRunnerHash -or
            $previousSuiteManifest.docker_fingerprint -ne $expectedDockerFingerprint -or
            $previousSuiteManifest.git_commit -ne $expectedGitCommit
        ) {
            throw 'Existing suite-manifest.json does not match the current experiment source, runner, Docker resources, or Git commit.'
        }
        $combinedVariants = @(
            @($previousSuiteManifest.variants) + @($Variants) |
                Sort-Object -Unique
        )
        $invocations = @($previousSuiteManifest.invocations) + @($currentInvocation)
        [ordered]@{
            schema_version = 1
            status = 'running'
            started_at = $previousSuiteManifest.started_at
            finished_at = $null
            variants = $combinedVariants
            source_fingerprint = $expectedSourceFingerprint
            benchmark_runner_sha256 = $expectedRunnerHash
            docker_fingerprint = $expectedDockerFingerprint
            git_commit = $expectedGitCommit
            comparison_report = $previousSuiteManifest.comparison_report
            invocations = $invocations
        }
    } else {
    [ordered]@{
        schema_version = 1
        status = 'running'
        started_at = $startedAt.ToString('o')
        finished_at = $null
        variants = @($Variants)
        source_fingerprint = $expectedSourceFingerprint
        benchmark_runner_sha256 = $expectedRunnerHash
        docker_fingerprint = $expectedDockerFingerprint
        git_commit = $expectedGitCommit
        comparison_report = $null
        invocations = @($currentInvocation)
    }
    }
}
if ($suiteManifest) {
    [IO.File]::WriteAllText(
        $suiteManifestPath,
        ($suiteManifest | ConvertTo-Json -Depth 8),
        [Text.UTF8Encoding]::new($false)
    )
    Write-Host "suite_manifest=$suiteManifestPath"
}

$restoreBaselineOnExit = $false
$comparisonGenerated = $false
try {
    Invoke-Project -Task 'preflight'
    Invoke-Project -Task 'verify-cluster'

    if ($ValidateOnly) {
        Assert-FrozenEnvironment
        Write-Host 'Windows suite validation completed; no experiment was started.'
        return
    }

    $restoreBaselineOnExit = $true

    foreach ($variant in $Variants) {
        Assert-FrozenEnvironment
        $variantOutput = Join-Path $resolvedResultsRoot $variant
        $manifestPath = Join-Path $variantOutput 'run-manifest.json'
        $manifest = if (Test-Path -LiteralPath $manifestPath) {
            Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        } else {
            $null
        }

        # Wrap the whole conditional so an empty directory remains an empty
        # array under StrictMode instead of collapsing to $null.
        $existingOutput = @(
            if (Test-Path -LiteralPath $variantOutput -PathType Container) {
                Get-ChildItem -LiteralPath $variantOutput -Force
            }
        )

        if (-not $manifest -and $existingOutput.Count -gt 0) {
            throw @"
Cannot start $variant because $variantOutput is non-empty but has no run-manifest.json.
Preserve or move that directory, then rerun the suite with a clean variant directory.
"@
        }

        Write-Host "`n=== WINDOWS EXPERIMENT: $variant ===" -ForegroundColor Cyan
        if ($manifest -and $manifest.status -eq 'completed') {
            Write-Host "$variant already completed; regenerating its derived report only."
            Invoke-Project -Task 'benchmark-analyze' -Variant $variant `
                -CommandResultsRoot $resolvedResultsRoot
            continue
        }

        if ($manifest) {
            $deployedVariant = Get-DeployedVariant
            if ($deployedVariant -ne $variant) {
                throw @"
Cannot resume $variant because the cluster currently serves $deployedVariant.
The partial run is bound to its original Pod UID. Preserve or move
$variantOutput and start that variant again in a fresh directory.
"@
            }
            Write-Host "Resuming partial variant $variant on its existing Pod."
        } else {
            Invoke-Project -Task 'deploy' -Variant $variant
        }

        Invoke-Project -Task 'wait'
        Invoke-Project -Task 'smoke'
        if ($variant -in @(
            'mtp-kv768-fp8-cpu8',
            'baseline-cpu8-fp8',
            'baseline-kv768-fp8-cpu8'
        ) -and -not $manifest) {
            Write-Host 'Running the FP8 startup/smoke C20 gate before the formal 700-request run.'
            Invoke-Project -Task 'benchmark-gate' -Variant $variant `
                -CommandResultsRoot $resolvedResultsRoot
        }

        Invoke-Project -Task 'benchmark' -Variant $variant `
            -CommandResultsRoot $resolvedResultsRoot
        Save-StartupEvidence -Variant $variant
    }

    # The last formal phase can run for several minutes. Recheck every frozen
    # input before deriving comparisons so a mid-phase environment change can
    # never be recorded as a completed controlled suite.
    Assert-FrozenEnvironment

    if (Test-CompleteResultMatrix) {
        Invoke-Project -Task 'benchmark-compare-windows-sequential' `
            -CommandResultsRoot $resolvedResultsRoot
        $comparisonGenerated = $true
    } elseif (Test-CompleteCpu8FactorScreen) {
        Invoke-Project -Task 'benchmark-compare-windows-cpu8-factors' `
            -CommandResultsRoot $resolvedResultsRoot
        foreach ($factorVariant in @(
            'baseline-cpu8',
            'mtp-cpu8',
            'baseline-kv768-cpu8',
            'baseline-cpu8-fp8',
            'baseline-kv768-fp8-cpu8'
        )) {
            if (-not (Test-Path -LiteralPath (Join-Path $resolvedResultsRoot $factorVariant))) {
                continue
            }
            Invoke-Project -Task 'benchmark-analyze' -Variant $factorVariant `
                -CommandResultsRoot $resolvedResultsRoot
        }
        $comparisonGenerated = $true
    } else {
        Write-Warning 'The result root does not contain a completed 5-stage Windows matrix; sequential comparison was skipped.'
    }

    Write-Host "`nRestoring the steady-state CPU8 baseline Deployment."
    Restore-Baseline
    $restoreBaselineOnExit = $false

    $elapsed = (Get-Date) - $startedAt
    Write-Host "suite_completed=$(Get-Date -Format o)"
    Write-Host "suite_elapsed=$($elapsed.ToString())"
    if ($comparisonGenerated) {
        $comparisonDirectory = if (Test-CompleteResultMatrix) {
            'comparison-sequential'
        } else {
            'comparison-cpu8-factors'
        }
        $comparisonReport = Join-Path $resolvedResultsRoot "$comparisonDirectory\REPORT.md"
        Write-Host "comparison_report=$comparisonReport"
        $suiteManifest.comparison_report = $comparisonReport
        $suiteManifest.invocations[-1].comparison_report = $comparisonReport
    } else {
        Write-Host 'comparison_report=skipped_incomplete_matrix'
    }
    $completedAt = (Get-Date).ToString('o')
    Assert-FrozenEnvironment
    $suiteManifest.status = 'completed'
    $suiteManifest.finished_at = $completedAt
    $suiteManifest.invocations[-1].status = 'completed'
    $suiteManifest.invocations[-1].finished_at = $completedAt
    [IO.File]::WriteAllText(
        $suiteManifestPath,
        ($suiteManifest | ConvertTo-Json -Depth 8),
        [Text.UTF8Encoding]::new($false)
    )
} finally {
    if ($restoreBaselineOnExit) {
        try {
            Write-Warning 'The suite did not complete; restoring the steady-state CPU8 baseline Deployment.'
            Restore-Baseline
            Write-Host 'Baseline recovery completed.'
        } catch {
            Write-Warning "Automatic baseline recovery failed: $($_.Exception.Message)"
        }
    }
    [void][WindowsBenchmark.PowerManagement]::SetThreadExecutionState($esContinuous)
}
