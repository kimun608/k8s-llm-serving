# syntax=docker/dockerfile:1.7

# vLLM v0.26.0 official Linux/ARM64 CPU image, pinned by digest.
FROM vllm/vllm-openai-cpu:v0.26.0-arm64@sha256:5966fcc14fe241ee7f2dc3d3fd5610ed12968eb9c0d096e1089802b79681efc4

ARG MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct
ARG MODEL_REVISION=7ae557604adf67be50417f59c2c2f167def9a775
ARG MODEL_DIR=/models/qwen2.5-0.5b-instruct

LABEL org.opencontainers.image.title="Local CPU vLLM Qwen2.5-0.5B server" \
      org.opencontainers.image.description="Reproducible ARM64 CPU-only vLLM image for local Kubernetes experiments" \
      org.opencontainers.image.version="vllm-0.26.0-qwen2.5-0.5b" \
      ai.vllm.version="0.26.0" \
      ai.model.id="${MODEL_ID}" \
      ai.model.revision="${MODEL_REVISION}"

# Bake the public model into the image. Kubernetes startup is then offline and
# model loading is not affected by Hugging Face network latency.
RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='${MODEL_ID}', revision='${MODEL_REVISION}', local_dir='${MODEL_DIR}')" \
    && test -s "${MODEL_DIR}/model.safetensors" \
    && test -s "${MODEL_DIR}/tokenizer.json"

ENV MODEL_DIR=/models/qwen2.5-0.5b-instruct \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    TOKENIZERS_PARALLELISM=false

EXPOSE 8000

# Explicitly override the upstream entrypoint so the same command can be used
# for Docker smoke tests and in Kubernetes.
ENTRYPOINT ["vllm", "serve"]
CMD ["/models/qwen2.5-0.5b-instruct", "--host", "0.0.0.0", "--port", "8000", "--served-model-name", "qwen2.5-0.5b-instruct", "--dtype", "float16", "--max-model-len", "2048", "--max-num-seqs", "20", "--max-num-batched-tokens", "2048", "--no-enable-prefix-caching"]
