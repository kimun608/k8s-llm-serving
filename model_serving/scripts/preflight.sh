#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "project_root=${project_root}"
echo "host_arch=$(uname -m)"
echo "host_os=$(sw_vers -productVersion 2>/dev/null || uname -s)"
echo "docker_client=$(docker version --format '{{.Client.Version}}')"
echo "docker_server=$(docker version --format '{{.Server.Version}}')"
docker info --format 'docker_arch={{.Architecture}} docker_cpus={{.NCPU}} docker_memory_bytes={{.MemTotal}}'
echo "kubectl_client=$(kubectl version --client -o json | jq -r '.clientVersion.gitVersion')"

if [[ -x "${project_root}/bin/kind" ]]; then
  echo "kind=$(${project_root}/bin/kind version)"
else
  echo "kind=not-installed (run: make install-kind)"
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This configuration is pinned for an Apple ARM64 host." >&2
  exit 1
fi

docker_arch="$(docker info --format '{{.Architecture}}')"
if [[ "${docker_arch}" != "aarch64" ]] && [[ "${docker_arch}" != "arm64" ]]; then
  echo "Docker must run Linux/ARM64 containers; detected ${docker_arch}." >&2
  exit 1
fi
