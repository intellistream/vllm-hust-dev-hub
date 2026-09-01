ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG VLLM_CORE_REPOSITORY
ARG VLLM_CORE_COMMIT
ARG VLLM_CORE_SOURCE_VERSION
ARG VLLM_CORE_PACKAGE_VERSION
ARG VLLM_ASCEND_REPOSITORY
ARG VLLM_ASCEND_COMMIT
ARG VLLM_ASCEND_SOURCE_VERSION
ARG VLLM_ASCEND_PACKAGE_VERSION
ARG VLLM_COMPATIBILITY_BASE
ARG RUNTIME_LOCK_SCHEMA
ARG BUILD_CREATED

COPY artifacts/ /tmp/runtime-wheels/
COPY production-lock.json /tmp/production-lock.json
COPY install_runtime_metadata.py /tmp/install_runtime_metadata.py

# Remove release packages inherited from the compatibility image. The final
# runtime contains only the hash-verified wheels staged by the lock builder.
RUN python3 -m pip uninstall -y vllm vllm-ascend triton-ascend triton torch-npu torch torchvision torchaudio \
    && python3 -c 'from pathlib import Path; import site; [(Path(root) / "vllm_hust_runtime_metadata.pth").unlink(missing_ok=True) for root in site.getsitepackages()]'
RUN source /usr/local/Ascend/ascend-toolkit/set_env.sh \
    && python3 -m pip install --no-index --find-links=/tmp/runtime-wheels \
         /tmp/runtime-wheels/numpy-2.2.6-*.whl \
         /tmp/runtime-wheels/torch-*.whl \
         /tmp/runtime-wheels/torch_npu-*.whl \
         /tmp/runtime-wheels/torchvision-*.whl \
         /tmp/runtime-wheels/torchaudio-*.whl \
         /tmp/runtime-wheels/triton-3.6.0-*.whl \
         /tmp/runtime-wheels/triton_ascend-*.whl \
         /tmp/runtime-wheels/transformers-5.14.1-*.whl \
         /tmp/runtime-wheels/huggingface_hub-1.29.0-*.whl \
         /tmp/runtime-wheels/starlette-1.0.1-*.whl \
         /tmp/runtime-wheels/fastapi-0.136.3-*.whl \
         /tmp/runtime-wheels/pyelftools-0.33-*.whl \
         /tmp/runtime-wheels/vllm-*.whl \
         /tmp/runtime-wheels/vllm_ascend-*.whl \
    && TORCH_DEVICE_BACKEND_AUTOLOAD=0 python3 /tmp/install_runtime_metadata.py \
         --lock /tmp/production-lock.json \
         --core-commit "${VLLM_CORE_COMMIT}" \
         --plugin-commit "${VLLM_ASCEND_COMMIT}" \
         --core-source-version "${VLLM_CORE_SOURCE_VERSION}" \
         --plugin-source-version "${VLLM_ASCEND_SOURCE_VERSION}" \
    && TORCH_DEVICE_BACKEND_AUTOLOAD=0 python3 -c 'import importlib.metadata as m, json, vllm, vllm_ascend; receipt=json.load(open("/opt/vllm-hust-runtime/runtime-stack.json")); assert vllm.__version__ == receipt["core"]["source_version"], (vllm.__version__, receipt["core"]); assert m.version("vllm") == receipt["core"]["package_version"]; eps=m.entry_points(); assert "ascend" in {e.name for e in eps.select(group="vllm.platform_plugins")}; from vllm.entrypoints.openai.api_server import build_app; assert callable(build_app)' \
    && rm -rf /tmp/runtime-wheels /tmp/install_runtime_metadata.py /tmp/production-lock.json

# Keep build timestamps in the final metadata-only layer so repeated
# validation builds can reuse the expensive package installation layer.
LABEL org.opencontainers.image.title="vLLM-HUST Ascend production runtime" \
      org.opencontainers.image.description="Immutable wheel runtime built from synchronized vLLM-HUST main commits" \
      ai.vllm-hust.runtime-lock.schema="${RUNTIME_LOCK_SCHEMA}" \
      ai.vllm-hust.vllm-core.repository="${VLLM_CORE_REPOSITORY}" \
      ai.vllm-hust.vllm-core.commit="${VLLM_CORE_COMMIT}" \
      ai.vllm-hust.vllm-core.source-version="${VLLM_CORE_SOURCE_VERSION}" \
      ai.vllm-hust.vllm-core.package-version="${VLLM_CORE_PACKAGE_VERSION}" \
      ai.vllm-hust.vllm-ascend.repository="${VLLM_ASCEND_REPOSITORY}" \
      ai.vllm-hust.vllm-ascend.commit="${VLLM_ASCEND_COMMIT}" \
      ai.vllm-hust.vllm-ascend.source-version="${VLLM_ASCEND_SOURCE_VERSION}" \
      ai.vllm-hust.vllm-ascend.package-version="${VLLM_ASCEND_PACKAGE_VERSION}" \
      ai.vllm-hust.compatibility.base="${VLLM_COMPATIBILITY_BASE}" \
      ai.vllm-hust.source-mode="immutable-wheels" \
      org.opencontainers.image.created="${BUILD_CREATED}" \
      org.opencontainers.image.revision="${VLLM_CORE_COMMIT}:${VLLM_ASCEND_COMMIT}"
