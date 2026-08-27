#!/usr/bin/env bash
set -euo pipefail

kind_version="${1:-v0.32.0}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bin_dir="${project_root}/bin"
kind_bin="${bin_dir}/kind"
download_url="https://kind.sigs.k8s.io/dl/${kind_version}/kind-darwin-arm64"
checksum_url="${download_url}.sha256sum"

mkdir -p "${bin_dir}"

if [[ -x "${kind_bin}" ]] && [[ "$("${kind_bin}" version 2>/dev/null)" == *"${kind_version}"* ]]; then
  echo "Kind ${kind_version} is already installed at ${kind_bin}"
  exit 0
fi

curl -fL --retry 3 -o "${kind_bin}" "${download_url}"
curl -fL --retry 3 -o "${kind_bin}.sha256sum" "${checksum_url}"

expected_checksum="$(awk '{print $1}' "${kind_bin}.sha256sum")"
actual_checksum="$(shasum -a 256 "${kind_bin}" | awk '{print $1}')"
if [[ "${expected_checksum}" != "${actual_checksum}" ]]; then
  echo "Kind checksum mismatch" >&2
  exit 1
fi

chmod +x "${kind_bin}"
"${kind_bin}" version
