[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:PATH = "$(Join-Path $projectRoot 'bin')$([IO.Path]::PathSeparator)$env:PATH"

function Invoke-Native {
    param([string[]]$ArgumentList)
    & kubectl @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl exited with code $LASTEXITCODE"
    }
}

Write-Host 'NODES'
Invoke-Native @('get', 'nodes', '-o', 'wide')

Write-Host "`nWORKLOADS"
Invoke-Native @('-n', 'llm-serving', 'get', 'deployment,pod,service', '-o', 'wide')

Write-Host "`nRECENT EVENTS"
$events = @(& kubectl -n llm-serving get events --sort-by=.metadata.creationTimestamp)
if ($LASTEXITCODE -ne 0) {
    throw "kubectl exited with code $LASTEXITCODE"
}
$events | Select-Object -Last 20
