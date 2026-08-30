[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$projectBin = Join-Path $projectRoot 'bin'
$env:PATH = "$projectBin$([IO.Path]::PathSeparator)$env:PATH"
$hostArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
$runningOnWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)

Write-Host "project_root=$projectRoot"
Write-Host "host_os=$([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)"
Write-Host "host_arch=$hostArchitecture"

if (-not $runningOnWindows) {
    throw 'project.ps1 is the Windows entry point. Use the Makefile workflow on macOS.'
}

foreach ($command in @('docker')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is not installed or is not available on PATH."
    }
}

if ($hostArchitecture -ne 'X64') {
    throw "The Windows workflow currently supports an x64 host; detected $hostArchitecture."
}

$dockerInfoJson = (& docker info --format '{{json .}}' 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $dockerInfoJson) {
    throw @'
Docker Desktop is installed but its Linux engine is not ready.
Start Docker Desktop and make sure WSL 2 / Virtual Machine Platform is enabled.
If Windows requests it, run `wsl --install --no-distribution` in an elevated
PowerShell, restart Windows, and then rerun: .\project.ps1 preflight
'@
}

$dockerInfo = $dockerInfoJson | ConvertFrom-Json
Write-Host "docker_server=$($dockerInfo.ServerVersion)"
Write-Host "docker_os=$($dockerInfo.OSType)"
Write-Host "docker_arch=$($dockerInfo.Architecture)"
Write-Host "docker_cpus=$($dockerInfo.NCPU)"
Write-Host "docker_memory_bytes=$($dockerInfo.MemTotal)"

if ($dockerInfo.OSType -ne 'linux') {
    throw "Docker Desktop must use Linux containers; detected $($dockerInfo.OSType)."
}
if ($dockerInfo.Architecture -notin @('x86_64', 'amd64')) {
    throw "Docker Desktop must expose linux/amd64 containers; detected $($dockerInfo.Architecture)."
}
if ([int]$dockerInfo.NCPU -lt 8) {
    throw "Docker exposes fewer than 8 CPUs. Allocate at least 8 CPUs before deploying vLLM."
}
if ([int64]$dockerInfo.MemTotal -lt 8GB) {
    throw "Docker has less than 8 GiB available. Allocate at least 8 GiB before deploying vLLM."
}
if ([int64]$dockerInfo.MemTotal -lt 12GB) {
    Write-Warning 'Docker has less than the recommended 12 GiB available; full benchmarks may be memory constrained.'
}

$kubectl = Get-Command kubectl.exe, kubectl -ErrorAction SilentlyContinue | Select-Object -First 1
if ($kubectl) {
    $kubectlVersionJson = (& $kubectl.Source version --client -o json | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw 'kubectl is installed but could not report its client version.'
    }
    $kubectlVersion = ($kubectlVersionJson | ConvertFrom-Json).clientVersion.gitVersion
    Write-Host "kubectl_client=$kubectlVersion"
} else {
    Write-Host 'kubectl=not-installed (run: .\project.ps1 install-kubectl)'
}

$kindPath = Join-Path $projectRoot 'bin\kind.exe'
if (Test-Path -LiteralPath $kindPath) {
    Write-Host "kind=$(& $kindPath version)"
} else {
    Write-Host 'kind=not-installed (run: .\project.ps1 install-kind)'
}

$pythonVersion = $null
$pythonPath = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
if (Test-Path -LiteralPath $pythonPath) {
    $pythonVersion = (& $pythonPath --version 2>&1 | Out-String).Trim()
} else {
    $python = Get-Command py.exe, python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($python) {
        $pythonVersion = (& $python.Source --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) {
            $pythonVersion = $null
        }
        $pythonPath = $python.Source
    }
}
if ($pythonVersion) {
    Write-Host "python=$pythonVersion path=$pythonPath"
} else {
    Write-Host 'python=not-installed (required only for benchmarks and report validation)'
}

Write-Host 'preflight=ok'
