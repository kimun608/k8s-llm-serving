[CmdletBinding()]
param(
    [string]$KindVersion = 'v0.32.0'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$binDirectory = Join-Path $projectRoot 'bin'
$kindPath = Join-Path $binDirectory 'kind.exe'
$downloadPath = Join-Path $binDirectory 'kind.exe.download'
$checksumPath = Join-Path $binDirectory 'kind.exe.sha256sum'
$downloadUrl = "https://kind.sigs.k8s.io/dl/$KindVersion/kind-windows-amd64"
$checksumUrl = "$downloadUrl.sha256sum"

New-Item -ItemType Directory -Path $binDirectory -Force | Out-Null

if (Test-Path -LiteralPath $kindPath) {
    try {
        $installedVersion = & $kindPath version 2>$null
        if ($LASTEXITCODE -eq 0 -and $installedVersion -match [regex]::Escape($KindVersion)) {
            Write-Host "Kind $KindVersion is already installed at $kindPath"
            exit 0
        }
    } catch {
        Write-Warning "Existing Kind executable is unusable and will be replaced: $($_.Exception.Message)"
    }
}

Write-Host "Downloading Kind $KindVersion for Windows AMD64..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath -UseBasicParsing -TimeoutSec 120
Invoke-WebRequest -Uri $checksumUrl -OutFile $checksumPath -UseBasicParsing -TimeoutSec 120

$expectedChecksum = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actualChecksum = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedChecksum -ne $actualChecksum) {
    Remove-Item -LiteralPath $downloadPath -Force -ErrorAction SilentlyContinue
    throw "Kind checksum mismatch: expected $expectedChecksum, received $actualChecksum"
}

Move-Item -LiteralPath $downloadPath -Destination $kindPath -Force
& $kindPath version
if ($LASTEXITCODE -ne 0) {
    throw 'The downloaded Kind executable could not be started.'
}
