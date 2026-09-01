ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG VLLM_CORE_REPOSITORY
ARG VLLM_CORE_COMMIT
ARG VLLM_CORE_SOURCE_VERSION
ARG VLLM_ASCEND_REPOSITORY
ARG VLLM_ASCEND_COMMIT
ARG VLLM_ASCEND_SOURCE_VERSION
ARG VLLM_COMPATIBILITY_BASE
ARG VLLM_BASE_PACKAGE_VERSION
ARG VLLM_ASCEND_BASE_PACKAGE_VERSION
ARG RUNTIME_LOCK_SCHEMA
ARG BUILD_CREATED

LABEL org.opencontainers.image.title="vLLM-HUST Ascend production runtime" \
      org.opencontainers.image.description="Official vLLM Ascend runtime paired with immutable vLLM-HUST source pins" \
      ai.vllm-hust.runtime-lock.schema="${RUNTIME_LOCK_SCHEMA}" \
      ai.vllm-hust.vllm-core.repository="${VLLM_CORE_REPOSITORY}" \
      ai.vllm-hust.vllm-core.commit="${VLLM_CORE_COMMIT}" \
      ai.vllm-hust.vllm-core.source-version="${VLLM_CORE_SOURCE_VERSION}" \
      ai.vllm-hust.vllm-ascend.repository="${VLLM_ASCEND_REPOSITORY}" \
      ai.vllm-hust.vllm-ascend.commit="${VLLM_ASCEND_COMMIT}" \
      ai.vllm-hust.vllm-ascend.source-version="${VLLM_ASCEND_SOURCE_VERSION}" \
      ai.vllm-hust.compatibility.base="${VLLM_COMPATIBILITY_BASE}" \
      ai.vllm-hust.compatibility.vllm-package="${VLLM_BASE_PACKAGE_VERSION}" \
      ai.vllm-hust.compatibility.vllm-ascend-package="${VLLM_ASCEND_BASE_PACKAGE_VERSION}" \
      org.opencontainers.image.created="${BUILD_CREATED}" \
      org.opencontainers.image.revision="${VLLM_CORE_COMMIT}:${VLLM_ASCEND_COMMIT}" \
      ai.vllm-hust.source-mode="locked-read-only-bind"

# Fail the build if a mutable registry tag or an incorrect base architecture
# supplied a different Python/Ascend compatibility stack.
RUN python3 -c 'import importlib.metadata as m; expected={"torch":"2.10.0+cpu","torch-npu":"2.10.0.post4","triton-ascend":"3.2.2","vllm-ascend":"0.23.0"}; actual={name:m.version(name) for name in expected}; assert actual == expected, (actual, expected)'

COPY install_runtime_metadata.py /tmp/install_runtime_metadata.py
RUN python3 /tmp/install_runtime_metadata.py \
      --core-version "${VLLM_CORE_SOURCE_VERSION}" \
      --plugin-version "${VLLM_ASCEND_SOURCE_VERSION}" \
      --core-commit "${VLLM_CORE_COMMIT}" \
      --plugin-commit "${VLLM_ASCEND_COMMIT}" \
      --compatibility-base "${VLLM_COMPATIBILITY_BASE}" \
    && rm /tmp/install_runtime_metadata.py \
    && TORCH_DEVICE_BACKEND_AUTOLOAD=0 python3 -c 'import importlib.metadata as m, json, vllm; stack=json.load(open("/opt/vllm-hust-runtime-metadata/runtime-stack.json")); expected={"vllm":stack["core"]["version"],"vllm-ascend":stack["plugin"]["version"]}; actual={name:m.version(name) for name in expected}; assert actual == expected, (actual, expected); assert vllm.__version__ == expected["vllm"], vllm.__version__'
