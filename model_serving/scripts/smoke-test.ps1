[CmdletBinding()]
param(
    [int]$LocalPort = 18000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:PATH = "$(Join-Path $projectRoot 'bin')$([IO.Path]::PathSeparator)$env:PATH"

$namespace = 'llm-serving'
$service = 'service/vllm-cpu'
$baseUrl = "http://127.0.0.1:$LocalPort"
$logId = [guid]::NewGuid().ToString('N')
$stdoutLog = Join-Path ([IO.Path]::GetTempPath()) "vllm-port-forward-$logId.stdout.log"
$stderrLog = Join-Path ([IO.Path]::GetTempPath()) "vllm-port-forward-$logId.stderr.log"
$process = $null

try {
    $process = Start-Process -FilePath 'kubectl.exe' `
        -ArgumentList @('-n', $namespace, 'port-forward', $service, "${LocalPort}:8000") `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    $forwardingReady = $false
    foreach ($attempt in 1..60) {
        if ($process.HasExited) {
            $details = (Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue)
            throw "kubectl port-forward exited before binding the local port. $details"
        }
        $forwardOutput = Get-Content -LiteralPath $stdoutLog -Raw -ErrorAction SilentlyContinue
        if ($forwardOutput -match 'Forwarding from ') {
            $forwardingReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $forwardingReady) {
        throw 'Timed out waiting for kubectl port-forward to bind the local port.'
    }

    $healthy = $false
    foreach ($attempt in 1..30) {
        if ($process.HasExited) {
            $details = (Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue)
            throw "kubectl port-forward exited early. $details"
        }
        try {
            $response = Invoke-WebRequest -Uri "$baseUrl/health" -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $healthy) {
        throw 'Timed out waiting for the forwarded vLLM health endpoint.'
    }

    Write-Host 'HEALTH'
    Write-Host 'HTTP 200'

    Write-Host 'MODELS'
    $models = Invoke-RestMethod -Uri "$baseUrl/v1/models" -TimeoutSec 10
    $models | ConvertTo-Json -Depth 20

    Write-Host 'CHAT COMPLETION'
    $requestBody = @{
        model = 'qwen3.5-0.8b'
        messages = @(@{ role = 'user'; content = 'Reply with exactly: CPU serving is ready' })
        temperature = 0
        max_tokens = 16
    } | ConvertTo-Json -Depth 5
    $completion = Invoke-RestMethod `
        -Uri "$baseUrl/v1/chat/completions" `
        -Method Post `
        -ContentType 'application/json' `
        -Body $requestBody `
        -TimeoutSec 120
    $completion | ConvertTo-Json -Depth 20
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit(5000) | Out-Null
    }
    Remove-Item -LiteralPath $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
}
