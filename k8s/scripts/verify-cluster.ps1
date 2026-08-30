[CmdletBinding()]
param(
    [string]$ClusterName = 'project-process',
    [string]$ImageReference = 'local/vllm-cpu:qwen3.5-0.8b-vllm0.26.0',
    [string]$KubernetesVersion = 'v1.32.11',
    [string]$KindNodeImage = 'kindest/node:v1.32.11@sha256:5fc52d52a7b9574015299724bd68f183702956aa4a2116ae75a63cb574b35af8'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:PATH = "$(Join-Path $projectRoot 'bin')$([IO.Path]::PathSeparator)$env:PATH"
$kindPath = Join-Path $projectRoot 'bin\kind.exe'
if (-not (Test-Path -LiteralPath $kindPath)) {
    throw "Kind is not installed at $kindPath. Run: .\project.ps1 install-kind"
}

function Invoke-Native {
    param([string]$FilePath, [string[]]$ArgumentList)
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

Write-Host 'KIND NODES'
$nodes = @(& $kindPath get nodes --name $ClusterName)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to list nodes for Kind cluster $ClusterName"
}
$nodes | ForEach-Object { Write-Host $_ }

$expectedNodes = @("$ClusterName-control-plane", "$ClusterName-worker")
foreach ($expectedNode in $expectedNodes) {
    if ($nodes -notcontains $expectedNode) {
        throw "Expected Kind node $expectedNode was not found."
    }
}

Write-Host "`nKUBERNETES MEMBERSHIP"
Invoke-Native 'kubectl' @('wait', '--for=condition=Ready', 'node', '--all', '--timeout=60s')
Invoke-Native 'kubectl' @('get', 'nodes', '-o', 'wide')

$kubernetesNodesJson = (& kubectl get nodes -o json | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to inspect Kubernetes node membership.'
}
$kubernetesNodeObjects = @((($kubernetesNodesJson | ConvertFrom-Json).items))
$kubernetesNodes = @($kubernetesNodeObjects | ForEach-Object { $_.metadata.name })
if ($kubernetesNodes.Count -ne $expectedNodes.Count) {
    throw "Expected exactly $($expectedNodes.Count) Kubernetes nodes; found $($kubernetesNodes.Count)."
}
foreach ($expectedNode in $expectedNodes) {
    if ($kubernetesNodes -notcontains $expectedNode) {
        throw "Kubernetes context does not contain expected node $expectedNode."
    }
    $nodeObject = $kubernetesNodeObjects | Where-Object { $_.metadata.name -eq $expectedNode } | Select-Object -First 1
    if ($nodeObject.status.nodeInfo.kubeletVersion -ne $KubernetesVersion) {
        throw "$expectedNode runs kubelet $($nodeObject.status.nodeInfo.kubeletVersion), expected $KubernetesVersion. Recreate the cluster."
    }
}
Write-Host "kubelet_version=$KubernetesVersion"

$workerNodeJson = (& kubectl get node "$ClusterName-worker" -o json | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect worker node $ClusterName-worker"
}
$workerNode = $workerNodeJson | ConvertFrom-Json
if ($workerNode.metadata.labels.'llm-serving.local/worker' -ne 'true') {
    throw "Worker node $ClusterName-worker is missing llm-serving.local/worker=true."
}
Write-Host 'worker_scheduling_label=llm-serving.local/worker=true'

Write-Host "`nKIND DOCKER NETWORK"
$networkIds = @()
foreach ($node in $nodes) {
    $inspectJson = (& docker inspect $node | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Docker node $node"
    }
    $inspect = @(($inspectJson | ConvertFrom-Json))[0]
    if ($inspect.Config.Image -ne $KindNodeImage) {
        throw "Docker node $node uses $($inspect.Config.Image), expected $KindNodeImage. Recreate the cluster."
    }
    $kindNetwork = $inspect.NetworkSettings.Networks.PSObject.Properties | Where-Object { $_.Name -eq 'kind' } | Select-Object -First 1
    if (-not $kindNetwork) {
        throw "Docker node $node is not attached to the kind network."
    }
    $networkIds += $kindNetwork.Value.NetworkID
    Write-Host "/$node network=kind ip=$($kindNetwork.Value.IPAddress)"
}
if (@($networkIds | Select-Object -Unique).Count -ne 1) {
    throw 'Kind nodes are not attached to the same Docker network instance.'
}

Write-Host "`nWORKER CNI AND KUBE-PROXY"
$systemPodsJson = (& kubectl -n kube-system get pods --field-selector "spec.nodeName=$ClusterName-worker" -o json | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect kube-system Pods on $ClusterName-worker."
}
$systemPods = @((($systemPodsJson | ConvertFrom-Json).items))
foreach ($requiredApp in @('kindnet', 'kube-proxy')) {
    $matchingPods = @($systemPods | Where-Object { $_.metadata.labels.'k8s-app' -eq $requiredApp })
    if (-not $matchingPods) {
        throw "$requiredApp Pod was not found on $ClusterName-worker."
    }
    foreach ($pod in $matchingPods) {
        $ready = @($pod.status.conditions | Where-Object { $_.type -eq 'Ready' -and $_.status -eq 'True' })
        if ($pod.status.phase -ne 'Running' -or -not $ready) {
            throw "Pod $($pod.metadata.name) is not Running and Ready."
        }
        Write-Host "$requiredApp=$($pod.metadata.name) Running/Ready"
    }
}

Write-Host "`nIMAGE IN EACH NODE CONTAINERD"
$localImageId = (& docker image inspect $ImageReference --format '{{.Id}}' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $localImageId) {
    throw "Local Docker image $ImageReference was not found."
}
$nodeImageReference = if ($ImageReference.StartsWith('docker.io/')) { $ImageReference } else { "docker.io/$ImageReference" }
foreach ($node in $nodes) {
    Write-Host "node=$node"
    $imageOutput = (& docker exec $node ctr -n k8s.io images inspect $nodeImageReference 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Image $ImageReference was not found in containerd on $node."
    }
    if ($imageOutput -notmatch [regex]::Escape($localImageId)) {
        throw "Image $ImageReference on $node does not match local image ID $localImageId."
    }
    Write-Host "image=$nodeImageReference id=$localImageId"
}
