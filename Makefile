SHELL := /bin/zsh
CAFFEINATE := $(shell command -v caffeinate 2>/dev/null)
KEEP_AWAKE := $(if $(CAFFEINATE),$(CAFFEINATE) -dimsu,)

PROJECT_ROOT := $(CURDIR)
K8S_DIR := $(PROJECT_ROOT)/k8s
MODEL_SERVING_DIR := $(PROJECT_ROOT)/model_serving
BENCHMARK_DIR := $(PROJECT_ROOT)/benchmark
RESULTS_ROOT ?= $(BENCHMARK_DIR)/results
KIND := $(PROJECT_ROOT)/bin/kind
KIND_VERSION := v0.32.0
CLUSTER_NAME := project-process
KIND_NODE_IMAGE := kindest/node:v1.32.11@sha256:5fc52d52a7b9574015299724bd68f183702956aa4a2116ae75a63cb574b35af8
IMAGE_REPOSITORY := local/vllm-cpu
IMAGE_TAG := qwen3.5-0.8b-vllm0.26.0
IMAGE := $(IMAGE_REPOSITORY):$(IMAGE_TAG)

.PHONY: help preflight install-kind image cluster load verify-cluster deploy deploy-baseline-cpu8 deploy-mtp deploy-mtp-kv-tuned wait status smoke benchmark-data benchmark-check benchmark-baseline benchmark-baseline-cpu8 benchmark-mtp benchmark-mtp-kv-tuned benchmark-analyze benchmark-compare benchmark-compare-cpu8 all clean-cluster

help:
	@echo "make preflight       Check the local environment"
	@echo "make install-kind    Download the pinned Kind binary into ./bin"
	@echo "make image           Build the ARM64 vLLM image with the MTP-capable model"
	@echo "make cluster         Create the pinned two-node Kind cluster"
	@echo "make load            Load the local image into Kind"
	@echo "make verify-cluster  Verify node join, network, and image presence"
	@echo "make deploy          Apply the baseline Kubernetes resources"
	@echo "make deploy-baseline-cpu8  Apply baseline with only CPU limit 8"
	@echo "make deploy-mtp      Apply native MTP optimization and wait"
	@echo "make deploy-mtp-kv-tuned  Apply MTP + 768MiB KV/24-seq optimization and wait"
	@echo "make wait            Wait until the vLLM Deployment is available"
	@echo "make status          Show nodes, Pods, Service, and recent events"
	@echo "make smoke           Test /health, /v1/models, and one completion"
	@echo "make benchmark-data  Build the fixed 100-prompt public benchmark workload"
	@echo "make benchmark-check Run a 20-request concurrency-20 functional check"
	@echo "make benchmark-baseline  Run 100 requests at C=1,2,5,10,20,50,100 and analyze"
	@echo "make benchmark-baseline-cpu8  Run the same matrix with only CPU limit 8"
	@echo "make benchmark-mtp       Run the same 700-request matrix against MTP"
	@echo "make benchmark-mtp-kv-tuned  Run the same matrix against both optimizations"
	@echo "make benchmark-analyze   Rebuild tables, SVG charts, and the report"
	@echo "make benchmark-compare   Validate and compare baseline, MTP, and final results"
	@echo "make benchmark-compare-cpu8  Validate the one-field CPU 6 vs 8 comparison"
	@echo "make all             Run install-kind, image, cluster, load, deploy, wait"
	@echo "make clean-cluster   Delete only the project-process Kind cluster"

preflight:
	@"$(MODEL_SERVING_DIR)/scripts/preflight.sh"

install-kind:
	@"$(K8S_DIR)/scripts/install-kind.sh" "$(KIND_VERSION)"

image:
	docker build --platform linux/arm64 --progress plain --tag "$(IMAGE)" "$(MODEL_SERVING_DIR)"
	docker image inspect "$(IMAGE)" --format 'image={{.RepoTags}} id={{.Id}} size={{.Size}} arch={{.Architecture}}'

cluster: install-kind
	"$(KIND)" create cluster --name "$(CLUSTER_NAME)" --image "$(KIND_NODE_IMAGE)" --config "$(K8S_DIR)/kind/cluster.yaml" --wait 180s

load:
	"$(KIND)" load docker-image "$(IMAGE)" --name "$(CLUSTER_NAME)"

verify-cluster:
	@"$(K8S_DIR)/scripts/verify-cluster.sh" "$(CLUSTER_NAME)" "$(IMAGE_REPOSITORY)"

deploy:
	kubectl apply -k "$(MODEL_SERVING_DIR)/k8s/overlays/baseline"

deploy-baseline-cpu8:
	kubectl apply -k "$(MODEL_SERVING_DIR)/k8s/overlays/baseline-cpu8"
	kubectl -n llm-serving rollout status deployment/vllm-cpu --timeout=300s

deploy-mtp:
	kubectl apply -k "$(MODEL_SERVING_DIR)/k8s/overlays/mtp"
	kubectl -n llm-serving rollout status deployment/vllm-cpu --timeout=300s

deploy-mtp-kv-tuned:
	kubectl apply -k "$(MODEL_SERVING_DIR)/k8s/overlays/mtp-kv-tuned"
	kubectl -n llm-serving rollout status deployment/vllm-cpu --timeout=300s

wait:
	kubectl -n llm-serving rollout status deployment/vllm-cpu --timeout=900s

status:
	@"$(MODEL_SERVING_DIR)/scripts/status.sh"

smoke:
	@"$(MODEL_SERVING_DIR)/scripts/smoke-test.sh"

benchmark-data:
	python3 "$(BENCHMARK_DIR)/scripts/prepare_dataset.py"

benchmark-check: benchmark-data
	@check_dir="$$(mktemp -d /tmp/k8s-llm-benchmark-check.XXXXXX)"; \
	python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/baseline.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$${check_dir}" --concurrencies 20 --limit 20; \
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$${check_dir}"; \
	echo "check_output=$${check_dir}"

benchmark-baseline: benchmark-data
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/baseline.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/baseline" --max-new-phases 4
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/baseline.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/baseline" --resume
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(RESULTS_ROOT)/baseline"

benchmark-baseline-cpu8: benchmark-data
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/baseline-cpu8.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/baseline-cpu8" --max-new-phases 4
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/baseline-cpu8.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/baseline-cpu8" --resume
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(RESULTS_ROOT)/baseline-cpu8"

benchmark-mtp: benchmark-data
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/mtp.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/mtp" --max-new-phases 4
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/mtp.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/mtp" --resume
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(RESULTS_ROOT)/mtp"

benchmark-mtp-kv-tuned: benchmark-data
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/mtp-kv-tuned.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/mtp-kv-tuned" --max-new-phases 4
	$(KEEP_AWAKE) python3 "$(BENCHMARK_DIR)/scripts/run_benchmark.py" \
		--config "$(BENCHMARK_DIR)/config/mtp-kv-tuned.json" \
		--prompts "$(BENCHMARK_DIR)/data/prompts.jsonl" \
		--output "$(RESULTS_ROOT)/mtp-kv-tuned" --resume
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(RESULTS_ROOT)/mtp-kv-tuned"

benchmark-analyze:
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(RESULTS_ROOT)/baseline"

benchmark-compare:
	python3 "$(BENCHMARK_DIR)/scripts/compare.py" \
		--results-root "$(RESULTS_ROOT)" \
		--output "$(RESULTS_ROOT)/comparison"

benchmark-compare-cpu8:
	python3 "$(BENCHMARK_DIR)/scripts/compare_cpu8.py" \
		--results-root "$(RESULTS_ROOT)" \
		--output "$(RESULTS_ROOT)/comparison-cpu8"

all: install-kind image cluster load verify-cluster deploy wait status

clean-cluster:
	"$(KIND)" delete cluster --name "$(CLUSTER_NAME)"
