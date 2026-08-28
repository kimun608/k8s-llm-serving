SHELL := /bin/zsh
CAFFEINATE := $(shell command -v caffeinate 2>/dev/null)
KEEP_AWAKE := $(if $(CAFFEINATE),$(CAFFEINATE) -dimsu,)

PROJECT_ROOT := $(CURDIR)
K8S_DIR := $(PROJECT_ROOT)/k8s
MODEL_SERVING_DIR := $(PROJECT_ROOT)/model_serving
BENCHMARK_DIR := $(PROJECT_ROOT)/benchmark
KIND := $(PROJECT_ROOT)/bin/kind
KIND_VERSION := v0.32.0
CLUSTER_NAME := project-process
KIND_NODE_IMAGE := kindest/node:v1.32.11@sha256:5fc52d52a7b9574015299724bd68f183702956aa4a2116ae75a63cb574b35af8
IMAGE_REPOSITORY := local/vllm-cpu
IMAGE_TAG := qwen3.5-0.8b-vllm0.26.0
IMAGE := $(IMAGE_REPOSITORY):$(IMAGE_TAG)

.PHONY: help preflight install-kind image cluster load verify-cluster deploy wait status smoke benchmark-data benchmark-check benchmark-baseline benchmark-analyze all clean-cluster

help:
	@echo "make preflight       Check the local environment"
	@echo "make install-kind    Download the pinned Kind binary into ./bin"
	@echo "make image           Build the ARM64 vLLM image with the MTP-capable model"
	@echo "make cluster         Create the pinned two-node Kind cluster"
	@echo "make load            Load the local image into Kind"
	@echo "make verify-cluster  Verify node join, network, and image presence"
	@echo "make deploy          Apply the baseline Kubernetes resources"
	@echo "make wait            Wait until the vLLM Deployment is available"
	@echo "make status          Show nodes, Pods, Service, and recent events"
	@echo "make smoke           Test /health, /v1/models, and one completion"
	@echo "make benchmark-data  Build the fixed 100-prompt public benchmark workload"
	@echo "make benchmark-check Run a 20-request concurrency-20 functional check"
	@echo "make benchmark-baseline  Run 100 requests at C=1,2,5,10,20,50,100 and analyze"
	@echo "make benchmark-analyze   Rebuild tables, SVG charts, and the report"
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
		--output "$(BENCHMARK_DIR)/results/baseline"
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(BENCHMARK_DIR)/results/baseline"

benchmark-analyze:
	python3 "$(BENCHMARK_DIR)/scripts/analyze.py" --input "$(BENCHMARK_DIR)/results/baseline"

all: install-kind image cluster load verify-cluster deploy wait status

clean-cluster:
	"$(KIND)" delete cluster --name "$(CLUSTER_NAME)"
