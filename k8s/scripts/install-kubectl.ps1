[CmdletBinding()]
param(
    [string]$KubernetesVersion = 'v1.32.11'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$binDirectory = Join-Path $projectRoot 'bin'
$kubectlPath = Join-Path $binDirectory 'kubectl.exe'
$downloadPath = Join-Path $binDirectory 'kubectl.exe.download'
$checksumPath = Join-Path $binDirectory 'kubectl.exe.sha256'
$downloadUrl = "https://dl.k8s.io/release/$KubernetesVersion/bin/windows/amd64/kubectl.exe"
$checksumUrl = "$downloadUrl.sha256"

New-Item -ItemType Directory -Path $binDirectory -Force | Out-Null

if (Test-Path -LiteralPath $kubectlPath) {
    try {
        $versionJson = (& $kubectlPath version --client -o json 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $versionJson) {
            $installedVersion = ($versionJson | ConvertFrom-Json).clientVersion.gitVersion
            if ($installedVersion -eq $KubernetesVersion) {
                Write-Host "kubectl $KubernetesVersion is already installed at $kubectlPath"
                exit 0
            }
        }
    } catch {
        Write-Warning "Existing kubectl executable is unusable and will be replaced: $($_.Exception.Message)"
    }
}

Write-Host "Downloading kubectl $KubernetesVersion for Windows AMD64..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath -UseBasicParsing -TimeoutSec 120
Invoke-WebRequest -Uri $checksumUrl -OutFile $checksumPath -UseBasicParsing -TimeoutSec 120

$expectedChecksum = (Get-Content -LiteralPath $checksumPath -Raw).Trim().ToLowerInvariant()
$actualChecksum = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedChecksum -ne $actualChecksum) {
    Remove-Item -LiteralPath $downloadPath -Force -ErrorAction SilentlyContinue
    throw "kubectl checksum mismatch: expected $expectedChecksum, received $actualChecksum"
}

Move-Item -LiteralPath $downloadPath -Destination $kubectlPath -Force
& $kubectlPath version --client
if ($LASTEXITCODE -ne 0) {
    throw 'The downloaded kubectl executable could not be started.'
}
