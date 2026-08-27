#!/usr/bin/env bash
set -euo pipefail

cluster_name="${1:-project-process}"
image_repository="${2:-local/vllm-cpu}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
kind_bin="${project_root}/bin/kind"

echo "KIND NODES"
"${kind_bin}" get nodes --name "${cluster_name}"
echo
echo "KUBERNETES MEMBERSHIP"
kubectl wait --for=condition=Ready node --all --timeout=60s
kubectl get nodes -o wide
echo
echo "KIND DOCKER NETWORK"
for node_name in $("${kind_bin}" get nodes --name "${cluster_name}"); do
  docker inspect "${node_name}" --format '{{.Name}} network={{range $network, $config := .NetworkSettings.Networks}}{{$network}} ip={{$config.IPAddress}}{{end}}'
done
echo
echo "IMAGE IN EACH NODE CONTAINERD"
for node_name in $("${kind_bin}" get nodes --name "${cluster_name}"); do
  echo "node=${node_name}"
  image_output="$(docker exec "${node_name}" crictl images)"
  echo "${image_output}" | awk -v repository="${image_repository}" 'NR == 1 || index($1, repository) > 0'
  if ! echo "${image_output}" | awk -v repository="${image_repository}" 'index($1, repository) > 0 { found=1 } END { exit !found }'; then
    echo "Image ${image_repository} was not found in node ${node_name}" >&2
    exit 1
  fi
done
