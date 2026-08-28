#!/usr/bin/env bash
set -euo pipefail

namespace="llm-serving"
service="service/vllm-cpu"
local_port="18000"
log_file="${TMPDIR:-/tmp}/vllm-port-forward.log"

kubectl -n "${namespace}" port-forward "${service}" "${local_port}:8000" >"${log_file}" 2>&1 &
port_forward_pid=$!
cleanup() {
  kill "${port_forward_pid}" 2>/dev/null || true
  wait "${port_forward_pid}" 2>/dev/null || true
}
trap cleanup EXIT

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${local_port}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "HEALTH"
health_code="$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${local_port}/health")"
if [[ "${health_code}" != "200" ]]; then
  echo "Expected HTTP 200 from /health, received ${health_code}" >&2
  exit 1
fi
echo "HTTP ${health_code}"
echo "MODELS"
curl -fsS "http://127.0.0.1:${local_port}/v1/models" | jq .
echo "CHAT COMPLETION"
curl -fsS "http://127.0.0.1:${local_port}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-0.8b","messages":[{"role":"user","content":"Reply with exactly: CPU serving is ready"}],"temperature":0,"max_tokens":16}' | jq .
