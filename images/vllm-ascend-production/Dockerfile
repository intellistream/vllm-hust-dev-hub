ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG VLLM_CORE_REPOSITORY
ARG VLLM_CORE_COMMIT
ARG VLLM_ASCEND_REPOSITORY
ARG VLLM_ASCEND_COMMIT
ARG RUNTIME_LOCK_SCHEMA

LABEL org.opencontainers.image.title="vLLM-HUST Ascend production runtime" \
      org.opencontainers.image.description="Official vLLM Ascend runtime paired with immutable vLLM-HUST source pins" \
      ai.vllm-hust.runtime-lock.schema="${RUNTIME_LOCK_SCHEMA}" \
      ai.vllm-hust.vllm-core.repository="${VLLM_CORE_REPOSITORY}" \
      ai.vllm-hust.vllm-core.commit="${VLLM_CORE_COMMIT}" \
      ai.vllm-hust.vllm-ascend.repository="${VLLM_ASCEND_REPOSITORY}" \
      ai.vllm-hust.vllm-ascend.commit="${VLLM_ASCEND_COMMIT}" \
      ai.vllm-hust.source-mode="locked-read-only-bind"

# Fail the build if a mutable registry tag or an incorrect base architecture
# supplied a different Python/Ascend compatibility stack.
RUN python3 -c 'import importlib.metadata as m; expected={"torch":"2.10.0+cpu","torch-npu":"2.10.0.post4","triton-ascend":"3.2.2","vllm-ascend":"0.23.0"}; actual={name:m.version(name) for name in expected}; assert actual == expected, (actual, expected)'
