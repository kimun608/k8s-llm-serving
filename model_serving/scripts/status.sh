#!/usr/bin/env bash
set -euo pipefail

echo "NODES"
kubectl get nodes -o wide
echo
echo "WORKLOADS"
kubectl -n llm-serving get deployment,pod,service -o wide
echo
echo "RECENT EVENTS"
kubectl -n llm-serving get events --sort-by=.metadata.creationTimestamp | tail -n 20
