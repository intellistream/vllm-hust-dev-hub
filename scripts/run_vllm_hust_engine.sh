#!/usr/bin/env bash
# run_vllm_hust_engine.sh — Launch vLLM-HUST from the host into a Docker
# container with the repo's standard Ascend/runtime guardrails.
#
# This script intentionally runs from the host and uses `docker exec`.  Do not
# start the service by opening an interactive shell inside the container and
# running vLLM by hand; that path is too easy to get wrong.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

load_dotenv() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    local key="${line%%=*}"
    key="${key// /}"
    [[ -z "$key" || -n "${!key:-}" ]] && continue
    export "$line"
  done < "$env_file"
}

load_dotenv "$repo_root/.env"

container="${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-vllm-ascend-dev}}"
container_image="${VLLM_ENGINE_IMAGE:-${IMAGE:-}}"
auto_create_container="${VLLM_ENGINE_AUTO_CREATE_CONTAINER:-true}"
container_non_interactive="${VLLM_ENGINE_CONTAINER_NON_INTERACTIVE:-1}"
model_path="${VLLM_ENGINE_MODEL_PATH:-${MODEL_ID:-/data/shared_models/modelscope_cache/Qwen/Qwen3-32B}}"
served_model_name="${VLLM_ENGINE_SERVED_MODEL_NAME:-${SERVED_MODEL_NAME:-qwen3-32b}}"
host="${VLLM_ENGINE_HOST:-${HOST:-0.0.0.0}}"
port="${VLLM_ENGINE_PORT:-${PORT:-8000}}"
tp_size="${VLLM_ENGINE_TP_SIZE:-${TP_SIZE:-4}}"
max_model_len="${VLLM_ENGINE_MAX_MODEL_LEN:-${MAX_MODEL_LEN:-32768}}"
max_num_batched_tokens="${VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS:-${MAX_NUM_BATCHED_TOKENS:-$max_model_len}}"
gpu_mem_util="${VLLM_ENGINE_GPU_MEM_UTIL:-${GPU_MEM_UTIL:-0.85}}"
max_num_seqs="${VLLM_ENGINE_MAX_NUM_SEQS:-${MAX_NUM_SEQS:-16}}"
dtype="${VLLM_ENGINE_DTYPE:-${DTYPE:-bfloat16}}"
load_format="${VLLM_ENGINE_LOAD_FORMAT:-${LOAD_FORMAT:-auto}}"
quantization="${VLLM_ENGINE_QUANTIZATION:-${QUANTIZATION:-}}"
vllm_bin="${VLLM_ENGINE_BIN:-vllm-hust}"
conda_env="${VLLM_ENGINE_CONDA_ENV:-${CONDA_ENV:-vllm-hust-dev}}"
api_key="${VLLM_HUST_API_KEY:-${VLLM_ENGINE_API_KEY:-}}"
replace_existing="${VLLM_ENGINE_REPLACE_EXISTING:-true}"
enable_prefix_caching="${VLLM_ENGINE_ENABLE_PREFIX_CACHING:-1}"
enable_chunked_prefill="${VLLM_ENGINE_ENABLE_CHUNKED_PREFILL:-1}"
enforce_eager="${VLLM_ENGINE_ENFORCE_EAGER:-0}"
expert_parallel="${VLLM_ENGINE_ENABLE_EXPERT_PARALLEL:-0}"
flashcomm1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-0}"
fused_mc2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-1}"
plugins="${VLLM_PLUGINS:-ascend}"
pythonpath="${VLLM_ENGINE_PYTHONPATH:-/workspace/vllm-hust:/workspace/vllm-ascend-hust:/workspace/segment-reuse/src}"
target_device="${VLLM_TARGET_DEVICE:-npu}"

if [[ -z "$api_key" || "$api_key" == "EMPTY" ]]; then
  echo "ERROR: vLLM-HUST must be started with a real API key." >&2
  echo "Set VLLM_HUST_API_KEY in .env; never use EMPTY." >&2
  exit 1
fi

if (( max_num_batched_tokens < max_model_len )); then
  max_num_batched_tokens="$max_model_len"
fi

npu_devices="${VLLM_ENGINE_NPU_DEVICES:-${ASCEND_RT_VISIBLE_DEVICES:-}}"
if [[ -z "$npu_devices" ]]; then
  if (( tp_size > 1 )); then
    npu_devices="$(seq -s, 0 $((tp_size - 1)))"
  else
    npu_devices="0"
  fi
fi

docker_cmd=(docker)
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found on PATH." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  if sudo -n docker info >/dev/null 2>&1; then
    docker_cmd=(sudo docker)
  else
    echo "ERROR: cannot access Docker socket; configure docker access or passwordless sudo." >&2
    exit 1
  fi
fi

container_is_running() {
  [[ "$("${docker_cmd[@]}" inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" == "true" ]]
}

ensure_container_ready() {
  if container_is_running; then
    return 0
  fi

  if [[ "$auto_create_container" != "true" && "$auto_create_container" != "1" ]]; then
    if "${docker_cmd[@]}" inspect "$container" >/dev/null 2>&1; then
      echo "ERROR: Docker container '$container' exists but is not running." >&2
    else
      echo "ERROR: Docker container '$container' not found." >&2
    fi
    echo "Set VLLM_ENGINE_AUTO_CREATE_CONTAINER=true or start the container first." >&2
    exit 1
  fi

  if [[ ! -x "$repo_root/scripts/ascend-official-container.sh" ]]; then
    echo "ERROR: container auto-bootstrap requires scripts/ascend-official-container.sh." >&2
    exit 1
  fi

  echo "[vllm-hust] container '$container' is absent or stopped; bootstrapping via dev-hub container manager."
  echo "[vllm-hust] image             = ${container_image:-auto-detect official Ascend image}"
  CONTAINER_NAME="$container" \
  IMAGE="$container_image" \
  VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE="$container_non_interactive" \
    "$repo_root/scripts/ascend-official-container.sh" start

  if ! container_is_running; then
    echo "ERROR: Docker container '$container' is still not running after bootstrap." >&2
    exit 1
  fi
}

ensure_container_ready

echo "[vllm-hust] container        = $container"
echo "[vllm-hust] image            = ${container_image:-auto-detect official Ascend image}"
echo "[vllm-hust] model_path       = $model_path"
echo "[vllm-hust] served_model_name = $served_model_name"
echo "[vllm-hust] host:port         = $host:$port"
echo "[vllm-hust] tp_size           = $tp_size"
echo "[vllm-hust] npu_devices       = $npu_devices"
echo "[vllm-hust] max_model_len     = $max_model_len"
echo "[vllm-hust] max_num_seqs      = $max_num_seqs"
echo "[vllm-hust] prefix_cache      = $enable_prefix_caching"
echo "[vllm-hust] chunked_prefill   = $enable_chunked_prefill"
echo "[vllm-hust] graph_mode        = $([[ "$enforce_eager" == "1" ]] && echo "OFF (--enforce-eager)" || echo "ON")"

if [[ "$replace_existing" == "true" ]]; then
  cleanup_script=$(cat <<'PY'
import os
import signal
import subprocess
import sys
import time

port = sys.argv[1]
rows = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True)
matches = []
for row in rows.splitlines():
    parts = row.strip().split(None, 1)
    if len(parts) != 2:
        continue
    pid_text, cmd = parts
    try:
        pid = int(pid_text)
    except ValueError:
        continue
    haystack = f" {cmd} "
    if "vllm" not in cmd or " serve " not in haystack:
        continue
    if f"--port {port}" not in cmd and f"--port={port}" not in cmd:
        continue
    if pid == os.getpid():
        continue
    matches.append(pid)

if matches:
    print(" ".join(str(pid) for pid in matches))
    for pid in matches:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(5)
    for pid in matches:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        os.kill(pid, signal.SIGKILL)
PY
)
  cleaned_pids=$("${docker_cmd[@]}" exec "$container" python3 -c "$cleanup_script" "$port" 2>/dev/null || true)
  if [[ -n "$cleaned_pids" ]]; then
    echo "[vllm-hust] stopped existing vLLM process(es) on port $port: $cleaned_pids"
  fi
fi

inner_script=$(cat <<'BASH'
set -euo pipefail

CONDA_ENV="__CONDA_ENV__"
if [[ -f /root/miniconda3/etc/profile.d/conda.sh ]]; then
  source /root/miniconda3/etc/profile.d/conda.sh
  conda activate "$CONDA_ENV"
elif [[ -f /opt/conda/etc/profile.d/conda.sh ]]; then
  source /opt/conda/etc/profile.d/conda.sh
  conda activate "$CONDA_ENV"
elif [[ -n "${CONDA_PREFIX:-}" ]]; then
  echo "[container] conda already active: $CONDA_PREFIX"
else
  echo "[container] WARNING: no conda activation path found; relying on current PATH" >&2
fi

if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi

if [[ -n "${HUST_ATB_SET_ENV:-}" && -f "${HUST_ATB_SET_ENV}" ]]; then
  set +u
  source "${HUST_ATB_SET_ENV}" --cxx_abi=1
  set -u
elif [[ -f /usr/local/Ascend/nnal/atb/set_env.sh ]]; then
  set +u
  source /usr/local/Ascend/nnal/atb/set_env.sh --cxx_abi=1
  set -u
fi

export VLLM_TARGET_DEVICE="__TARGET_DEVICE__"
export ASCEND_RT_VISIBLE_DEVICES="__NPU_DEVICES__"
export ASCEND_VISIBLE_DEVICES="__NPU_DEVICES__"
export HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"
export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
export VLLM_PLUGINS="${VLLM_PLUGINS:-__PLUGINS__}"
export VLLM_ASCEND_ENABLE_FLASHCOMM1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-__FLASHCOMM1__}"
export VLLM_ASCEND_ENABLE_FUSED_MC2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-__FUSED_MC2__}"
export VLLM_ASCEND_TORCH_PREFLIGHT="${VLLM_ASCEND_TORCH_PREFLIGHT:-0}"
export COMPILE_CUSTOM_KERNELS="${COMPILE_CUSTOM_KERNELS:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export PYTHONPATH="__PYTHONPATH__:${PYTHONPATH:-}"

torch_lib="$(python3 -c 'import os, torch; print(os.path.join(os.path.dirname(torch.__file__), "lib"))' 2>/dev/null || true)"
torch_npu_lib="$(python3 -c 'import os, torch_npu; print(os.path.join(os.path.dirname(torch_npu.__file__), "lib"))' 2>/dev/null || true)"
if [[ -n "$torch_lib" || -n "$torch_npu_lib" ]]; then
  export LD_LIBRARY_PATH="${torch_lib:-}:${torch_npu_lib:-}:${LD_LIBRARY_PATH:-}"
fi

export HOME="${VLLM_ENGINE_CONTAINER_HOME:-/tmp/vllm-hust-home}"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export VLLM_CACHE_ROOT="$HOME/.cache/vllm"
export VLLM_CONFIG_ROOT="$HOME/.config/vllm"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$VLLM_CACHE_ROOT" "$VLLM_CONFIG_ROOT"

VLLM_BIN="__VLLM_BIN__"
if ! command -v "$VLLM_BIN" >/dev/null 2>&1; then
  VLLM_BIN="$(command -v vllm-hust 2>/dev/null || command -v vllm 2>/dev/null || true)"
fi
if [[ -z "$VLLM_BIN" ]]; then
  echo "ERROR: neither requested vLLM binary nor vllm-hust/vllm found in container PATH" >&2
  exit 1
fi

echo "[container] using vLLM binary: $VLLM_BIN"
echo "[container] python: $(command -v python3)"
echo "[container] vllm: $(python3 -c 'import vllm; print(vllm.__file__)' 2>/dev/null || echo 'N/A')"
echo "[container] vllm_ascend: $(python3 -c 'import vllm_ascend; print(vllm_ascend.__file__)' 2>/dev/null || echo 'N/A')"

args=(
  "$VLLM_BIN" serve "__MODEL_PATH__"
  --served-model-name "__SERVED_MODEL_NAME__"
  --host "__HOST__"
  --port "__PORT__"
  --tensor-parallel-size "__TP_SIZE__"
  --max-model-len "__MAX_MODEL_LEN__"
  --max-num-batched-tokens "__MAX_NUM_BATCHED_TOKENS__"
  --gpu-memory-utilization "__GPU_MEM_UTIL__"
  --dtype "__DTYPE__"
  --load-format "__LOAD_FORMAT__"
  --trust-remote-code
  --max-num-seqs "__MAX_NUM_SEQS__"
  --api-key "__API_KEY__"
)

[[ "__ENABLE_PREFIX_CACHING__" == "1" ]] && args+=(--enable-prefix-caching)
[[ "__ENABLE_CHUNKED_PREFILL__" == "1" ]] && args+=(--enable-chunked-prefill)
[[ "__ENFORCE_EAGER__" == "1" ]] && args+=(--enforce-eager)
[[ "__EXPERT_PARALLEL__" == "1" ]] && args+=(--enable-expert-parallel)
[[ -n "__QUANTIZATION__" ]] && args+=(--quantization "__QUANTIZATION__")

exec "${args[@]}"
BASH
)

replace() {
  local needle="$1"
  local value="$2"
  inner_script="${inner_script//"$needle"/"$value"}"
}

replace "__CONDA_ENV__" "$conda_env"
replace "__TARGET_DEVICE__" "$target_device"
replace "__NPU_DEVICES__" "$npu_devices"
replace "__PLUGINS__" "$plugins"
replace "__FLASHCOMM1__" "$flashcomm1"
replace "__FUSED_MC2__" "$fused_mc2"
replace "__PYTHONPATH__" "$pythonpath"
replace "__VLLM_BIN__" "$vllm_bin"
replace "__MODEL_PATH__" "$model_path"
replace "__SERVED_MODEL_NAME__" "$served_model_name"
replace "__HOST__" "$host"
replace "__PORT__" "$port"
replace "__TP_SIZE__" "$tp_size"
replace "__MAX_MODEL_LEN__" "$max_model_len"
replace "__MAX_NUM_BATCHED_TOKENS__" "$max_num_batched_tokens"
replace "__GPU_MEM_UTIL__" "$gpu_mem_util"
replace "__DTYPE__" "$dtype"
replace "__LOAD_FORMAT__" "$load_format"
replace "__MAX_NUM_SEQS__" "$max_num_seqs"
replace "__API_KEY__" "$api_key"
replace "__ENABLE_PREFIX_CACHING__" "$enable_prefix_caching"
replace "__ENABLE_CHUNKED_PREFILL__" "$enable_chunked_prefill"
replace "__ENFORCE_EAGER__" "$enforce_eager"
replace "__EXPERT_PARALLEL__" "$expert_parallel"
replace "__QUANTIZATION__" "$quantization"

tmp_host_script="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/vllm-hust-engine.XXXXXX.sh")"
cleanup() {
  rm -f "$tmp_host_script"
}
trap cleanup EXIT

printf '#!/usr/bin/env bash\n%s\n' "$inner_script" > "$tmp_host_script"
chmod +x "$tmp_host_script"

container_script="/tmp/$(basename "$tmp_host_script")"
"${docker_cmd[@]}" cp "$tmp_host_script" "$container:$container_script"

exec "${docker_cmd[@]}" exec \
  --env "VLLM_TARGET_DEVICE=$target_device" \
  --env "ASCEND_RT_VISIBLE_DEVICES=$npu_devices" \
  --env "ASCEND_VISIBLE_DEVICES=$npu_devices" \
  "$container" bash "$container_script"
