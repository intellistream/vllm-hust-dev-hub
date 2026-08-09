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
  local overwrite="${2:-false}"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    local key="${line%%=*}"
    key="${key// /}"
    [[ -z "$key" ]] && continue
    [[ "$overwrite" != "true" && -n "${!key:-}" ]] && continue
    export "$line"
  done < "$env_file"
}

if [[ "${VLLM_ENGINE_LOAD_REPO_ENV:-true}" != "false" && "${VLLM_ENGINE_LOAD_REPO_ENV:-true}" != "0" ]]; then
  load_dotenv "$repo_root/.env"
fi
if [[ -n "${VLLM_ENGINE_ENV_FILE:-}" ]]; then
  load_dotenv "$VLLM_ENGINE_ENV_FILE" true
fi

container="${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-vllm-ascend-dev}}"
container_image="${VLLM_ENGINE_IMAGE:-${IMAGE:-quay.io/ascend/vllm-ascend:v0.21.0rc1-openeuler}}"
auto_create_container="${VLLM_ENGINE_AUTO_CREATE_CONTAINER:-true}"
container_non_interactive="${VLLM_ENGINE_CONTAINER_NON_INTERACTIVE:-1}"
recreate_container="${VLLM_ENGINE_RECREATE_CONTAINER:-false}"
model_path="${VLLM_ENGINE_MODEL_PATH:-${MODEL_ID:-}}"
served_model_name="${VLLM_ENGINE_SERVED_MODEL_NAME:-${SERVED_MODEL_NAME:-}}"
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
compilation_config="${VLLM_ENGINE_COMPILATION_CONFIG:-}"
vllm_compat_version="${VLLM_ENGINE_VLLM_VERSION:-}"
vllm_bin="${VLLM_ENGINE_BIN:-vllm-hust}"
vllm_script="${VLLM_ENGINE_SCRIPT:-}"
conda_prefix="${VLLM_ENGINE_CONDA_PREFIX:-}"
conda_env="${VLLM_ENGINE_CONDA_ENV:-${CONDA_ENV:-vllm-hust-dev}}"
engine_python="${VLLM_ENGINE_PYTHON:-}"
api_key="${VLLM_HUST_API_KEY:-${VLLM_ENGINE_API_KEY:-}}"
replace_existing="${VLLM_ENGINE_REPLACE_EXISTING:-true}"
enable_prefix_caching="${VLLM_ENGINE_ENABLE_PREFIX_CACHING:-1}"
enable_chunked_prefill="${VLLM_ENGINE_ENABLE_CHUNKED_PREFILL:-1}"
enforce_eager="${VLLM_ENGINE_ENFORCE_EAGER:-0}"
expert_parallel="${VLLM_ENGINE_ENABLE_EXPERT_PARALLEL:-0}"
flashcomm1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-0}"
fused_mc2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-1}"
optimization_repo_container="${VLLM_OPTIMIZATION_REPO_CONTAINER:-}"
optimization_src_subdir="${VLLM_OPTIMIZATION_SRC_SUBDIR:-src}"
optimization_plugin="${VLLM_OPTIMIZATION_PLUGIN:-}"
optimization_env_prefix="${VLLM_OPTIMIZATION_ENV_PREFIX:-}"
plugins="${VLLM_PLUGINS:-}"
if [[ -z "$plugins" ]]; then
  plugins="ascend"
  if [[ -n "$optimization_plugin" ]]; then
    plugins="${plugins},${optimization_plugin}"
  fi
fi
container_workspace_root="${CONTAINER_WORKSPACE_ROOT:-/workspace}"
engine_base_pythonpath="${VLLM_ENGINE_BASE_PYTHONPATH-/workspace/vllm-hust:/workspace/vllm-ascend-hust}"
pythonpath="${VLLM_ENGINE_PYTHONPATH:-}"
if [[ -z "$pythonpath" ]]; then
  pythonpath="$engine_base_pythonpath"
  if [[ -n "$optimization_repo_container" ]]; then
    opt_pythonpath="$optimization_repo_container"
    if [[ -n "$optimization_src_subdir" ]]; then
      opt_pythonpath="${optimization_repo_container%/}/${optimization_src_subdir}:$opt_pythonpath"
    fi
    if [[ -n "$pythonpath" ]]; then
      pythonpath="$opt_pythonpath:$pythonpath"
    else
      pythonpath="$opt_pythonpath"
    fi
  fi
fi
if [[ -n "$optimization_env_prefix" && -z "${VLLM_ENGINE_EXTRA_ENV_PREFIXES:-}" ]]; then
  export VLLM_ENGINE_EXTRA_ENV_PREFIXES="$optimization_env_prefix"
fi
target_device="${VLLM_TARGET_DEVICE:-npu}"
container_log_file="${VLLM_ENGINE_CONTAINER_LOG_FILE:-}"
simple_kv_offload="${VLLM_USE_SIMPLE_KV_OFFLOAD:-0}"

container_extra_env_exports() {
  python3 - <<'PY'
import os
import shlex

explicit = {
    "COMPILE_CUSTOM_KERNELS",
    "HF_HUB_OFFLINE",
    "HF_ENDPOINT",
    "HF_HOME",
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_CACHE",
    "HF_DATASETS_CACHE",
    "HCCL_OP_EXPANSION_MODE",
    "PYTORCH_NPU_ALLOC_CONF",
    "TORCH_DEVICE_BACKEND_AUTOLOAD",
    "TRANSFORMERS_OFFLINE",
    "VLLM_ASCEND_TORCH_PREFLIGHT",
    "VLLM_ENGINE_EXTRA_ARGS_JSON",
    "VLLM_USE_SIMPLE_KV_OFFLOAD",
    "VLLM_USE_V1",
}
prefixes = ()
extra_keys = {
    item.strip()
    for item in os.environ.get("VLLM_ENGINE_EXTRA_ENV_KEYS", "").split(",")
    if item.strip()
}
extra_prefixes = tuple(
    item.strip()
    for item in os.environ.get("VLLM_ENGINE_EXTRA_ENV_PREFIXES", "").split(",")
    if item.strip()
)
safe_token_keys = {
    "MAX_NUM_BATCHED_TOKENS",
    "VLLM_ENGINE_MAX_NUM_BATCHED_TOKENS",
}

keys = []
for key in os.environ:
    upper = key.upper()
    if (
        key not in safe_token_keys
        and ("KEY" in upper or "TOKEN" in upper or "SECRET" in upper)
    ):
        continue
    if (
        key in explicit
        or key in extra_keys
        or key.startswith(prefixes)
        or key.startswith(extra_prefixes)
    ):
        keys.append(key)

for key in sorted(keys):
    print(f"export {key}={shlex.quote(os.environ[key])}")
PY
}

extra_env_exports="$(container_extra_env_exports)"

if [[ -z "$api_key" || "$api_key" == "EMPTY" ]]; then
  echo "ERROR: vLLM-HUST must be started with a real API key." >&2
  echo "Set VLLM_HUST_API_KEY in .env; never use EMPTY." >&2
  exit 1
fi
if [[ -z "$model_path" ]]; then
  echo "ERROR: VLLM_ENGINE_MODEL_PATH or MODEL_ID must be set." >&2
  echo "Put model/topology choices in VLLM_ENGINE_ENV_FILE profiles or a local .env." >&2
  exit 1
fi
if [[ -z "$served_model_name" ]]; then
  served_model_name="$(basename "$model_path")"
fi

if (( max_num_batched_tokens < max_model_len )); then
  max_num_batched_tokens="$max_model_len"
fi

npu_devices="${VLLM_ENGINE_NPU_DEVICES:-${ASCEND_RT_VISIBLE_DEVICES:-}}"
if [[ -z "$npu_devices" ]]; then
  echo "ERROR: VLLM_ENGINE_NPU_DEVICES or ASCEND_RT_VISIBLE_DEVICES must be set." >&2
  echo "Select devices through the deployment profile; the launcher does not choose physical NPUs." >&2
  exit 1
fi
runtime_visible_devices="${VLLM_ENGINE_RUNTIME_VISIBLE_DEVICES:-$npu_devices}"

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
  if [[ "$recreate_container" == "true" || "$recreate_container" == "1" ]]; then
    if "${docker_cmd[@]}" inspect "$container" >/dev/null 2>&1; then
      echo "[vllm-hust] recreating container '$container' via dev-hub launcher policy."
      "${docker_cmd[@]}" rm -f "$container" >/dev/null
    fi
  fi

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
echo "[vllm-hust] runtime_devices   = $runtime_visible_devices"
echo "[vllm-hust] max_model_len     = $max_model_len"
echo "[vllm-hust] max_num_seqs      = $max_num_seqs"
echo "[vllm-hust] prefix_cache      = $enable_prefix_caching"
echo "[vllm-hust] chunked_prefill   = $enable_chunked_prefill"
echo "[vllm-hust] graph_mode        = $([[ "$enforce_eager" == "1" ]] && echo "OFF (--enforce-eager)" || echo "ON")"
if [[ -n "$compilation_config" ]]; then
  echo "[vllm-hust] compilation_config = set"
fi
echo "[vllm-hust] plugins          = $plugins"
if [[ -n "$vllm_compat_version" ]]; then
  echo "[vllm-hust] vllm_compat      = $vllm_compat_version"
fi

if [[ "$replace_existing" == "true" ]]; then
cleanup_script='
port="$1"
all=""
for _ in 1 2 3; do
  matches="$(ps -eo pid=,args= | awk -v port="$port" '"'"'
    /vllm/ && / serve / {
      if ($0 ~ ("--port " port) || $0 ~ ("--port=" port)) {
        print $1
      }
    }
  '"'"' | tr "\n" " ")"
  launchers="$(ps -eo pid=,args= | awk '"'"'
    /bash \/tmp\/vllm-hust-engine\.[A-Za-z0-9]+\.sh/ {
      print $1
    }
  '"'"' | tr "\n" " ")"
  matches="$matches $launchers"
  if [ "${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-0}" = "1" ] || [ "${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-false}" = "true" ]; then
    orphans="$(ps -eo pid=,args= | awk '"'"'
      /VLLM::EngineCor|VLLM::Worker_TP|multiprocessing\.resource_tracker|multiprocessing\.spawn|\[python3\]/ {
        print $1
      }
    '"'"' | tr "\n" " ")"
    matches="$matches $orphans"
  fi
  if [ -z "$matches" ]; then
    continue
  fi
  all="$all $matches"
  kill $matches 2>/dev/null || true
  sleep 2
  kill -9 $matches 2>/dev/null || true
done
if [ -n "$all" ]; then
  echo "$all"
fi
'
  cleaned_pids=$("${docker_cmd[@]}" exec --env "VLLM_ENGINE_AGGRESSIVE_CLEANUP=${VLLM_ENGINE_AGGRESSIVE_CLEANUP:-0}" "$container" sh -c "$cleanup_script" sh "$port" 2>/dev/null || true)
  if [[ -n "$cleaned_pids" ]]; then
    echo "[vllm-hust] stopped existing vLLM process(es) on port $port: $cleaned_pids"
  fi
fi

inner_script=$(cat <<'BASH'
set -euo pipefail

__EXTRA_ENV_EXPORTS__

CONTAINER_LOG_FILE="__CONTAINER_LOG_FILE__"
if [[ -n "$CONTAINER_LOG_FILE" ]]; then
  mkdir -p "$(dirname "$CONTAINER_LOG_FILE")"
  exec > >(sed -E 's/sk-[A-Za-z0-9._-]+/<redacted>/g; s/(api-key[ =])[^ ]+/\1<redacted>/Ig; s/(Bearer )[A-Za-z0-9._~+\/-]+/\1<redacted>/g; s/([A-Za-z_]*(KEY|TOKEN|SECRET)[A-Za-z_]*=)[^ ]+/\1<redacted>/g' | tee -a "$CONTAINER_LOG_FILE") 2>&1
fi

CONDA_ENV="__CONDA_ENV__"
CONDA_PREFIX_OVERRIDE="__CONDA_PREFIX__"
ENGINE_PYTHON="__ENGINE_PYTHON__"
ENGINE_PYTHON_OVERRIDE="$ENGINE_PYTHON"
if [[ -n "$CONDA_PREFIX_OVERRIDE" ]]; then
  export CONDA_PREFIX="$CONDA_PREFIX_OVERRIDE"
  export PATH="$CONDA_PREFIX/bin:$PATH"
  export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
elif [[ -f /root/miniconda3/etc/profile.d/conda.sh ]]; then
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
if [[ -n "$ENGINE_PYTHON" ]]; then
  if [[ ! -x "$ENGINE_PYTHON" ]]; then
    echo "ERROR: VLLM_ENGINE_PYTHON is not executable in the container: $ENGINE_PYTHON" >&2
    exit 1
  fi
else
  ENGINE_PYTHON="$(command -v python3)"
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
export TORCH_DEVICE_BACKEND_AUTOLOAD="${TORCH_DEVICE_BACKEND_AUTOLOAD:-1}"
if [[ -n "${HCCL_OP_EXPANSION_MODE:-}" ]]; then
  export HCCL_OP_EXPANSION_MODE
fi
export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
export VLLM_PLUGINS="${VLLM_PLUGINS:-__PLUGINS__}"
export VLLM_ASCEND_ENABLE_FLASHCOMM1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-__FLASHCOMM1__}"
export VLLM_ASCEND_ENABLE_FUSED_MC2="${VLLM_ASCEND_ENABLE_FUSED_MC2:-__FUSED_MC2__}"
export VLLM_ASCEND_TORCH_PREFLIGHT="${VLLM_ASCEND_TORCH_PREFLIGHT:-0}"
export COMPILE_CUSTOM_KERNELS="${COMPILE_CUSTOM_KERNELS:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export PYTHONPATH="__PYTHONPATH__:${PYTHONPATH:-}"
if [[ -n "__VLLM_VERSION__" ]]; then
  export VLLM_VERSION="__VLLM_VERSION__"
fi

repair_editable_imports() {
  local workspace_root="$1"
  local site_roots
  local root
  local finder_file

  if [[ -z "$workspace_root" ]]; then
    workspace_root="/workspace"
  fi
  site_roots="$("$ENGINE_PYTHON" - <<'PY'
import site
for path in site.getsitepackages():
    if "site-packages" in path:
        print(path)
PY
)"

  for root in $site_roots; do
    for finder_file in "$root"/__editable___vllm*_finder.py; do
      [[ -f "$finder_file" ]] || continue
      "$ENGINE_PYTHON" - "$finder_file" "$workspace_root" <<'PY'
import pathlib
import sys

finder_file = pathlib.Path(sys.argv[1])
workspace_root = sys.argv[2].rstrip("/")
text = finder_file.read_text()
text = text.replace(
    "/vllm-workspace/vllm/vllm", f"{workspace_root}/vllm-hust/vllm"
)
text = text.replace(
    "/vllm-workspace/vllm-ascend/vllm_ascend",
    f"{workspace_root}/vllm-ascend-hust/vllm_ascend",
)
finder_file.write_text(text)
PY
    done
  done
}

repair_editable_imports "__CONTAINER_WORKSPACE_ROOT__"

if [[ "${VLLM_ENGINE_DISCOVER_TORCH_LIBS:-0}" == "1" ]]; then
  torch_lib="$("$ENGINE_PYTHON" -c 'import os, torch; print(os.path.join(os.path.dirname(torch.__file__), "lib"))' 2>/dev/null || true)"
  torch_npu_lib="$("$ENGINE_PYTHON" -c 'import os, torch_npu; print(os.path.join(os.path.dirname(torch_npu.__file__), "lib"))' 2>/dev/null || true)"
  if [[ -n "$torch_lib" || -n "$torch_npu_lib" ]]; then
    export LD_LIBRARY_PATH="${torch_lib:-}:${torch_npu_lib:-}:${LD_LIBRARY_PATH:-}"
  fi
fi

if [[ "${VLLM_ASCEND_TORCH_PREFLIGHT:-0}" == "1" ]]; then
  "$ENGINE_PYTHON" - <<'PY'
import torch
import torch_npu  # noqa: F401

print("[container] torch:", torch.__file__)
print("[container] torch_npu:", torch_npu.__file__)
print("[container] torch.npu.is_available:", torch.npu.is_available())
torch.npu.set_device("npu:0")
probe = torch.zeros(1, device="npu:0")
print("[container] torch_npu_preflight: ok shape=%s device=%s" % (tuple(probe.shape), probe.device))
PY
fi

export HOME="${VLLM_ENGINE_CONTAINER_HOME:-/tmp/vllm-hust-home}"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export VLLM_CACHE_ROOT="$HOME/.cache/vllm"
export VLLM_CONFIG_ROOT="$HOME/.config/vllm"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$VLLM_CACHE_ROOT" "$VLLM_CONFIG_ROOT"

VLLM_BIN="__VLLM_BIN__"
VLLM_SCRIPT="__VLLM_SCRIPT__"
if [[ -n "$VLLM_SCRIPT" ]]; then
  if [[ -x "$VLLM_BIN" ]]; then
    :
  elif command -v "$VLLM_BIN" >/dev/null 2>&1; then
    VLLM_BIN="$(command -v "$VLLM_BIN")"
  fi
  if [[ ! -x "$VLLM_BIN" ]]; then
    echo "ERROR: VLLM_ENGINE_BIN is not executable in the container: $VLLM_BIN" >&2
    exit 1
  fi
  if [[ ! -f "$VLLM_SCRIPT" ]]; then
    echo "ERROR: VLLM_ENGINE_SCRIPT does not exist in the container: $VLLM_SCRIPT" >&2
    exit 1
  fi
  echo "[container] using vLLM launcher: $VLLM_BIN $VLLM_SCRIPT"
elif [[ -n "$ENGINE_PYTHON_OVERRIDE" ]]; then
  VLLM_BIN="$(dirname "$ENGINE_PYTHON")/vllm"
  if [[ ! -f "$VLLM_BIN" ]]; then
    echo "ERROR: expected vLLM script next to VLLM_ENGINE_PYTHON, but not found: $VLLM_BIN" >&2
    exit 1
  fi
  echo "[container] using vLLM binary: $VLLM_BIN"
else
  if command -v "$VLLM_BIN" >/dev/null 2>&1; then
    VLLM_BIN="$(command -v "$VLLM_BIN")"
  else
    VLLM_BIN="$(command -v vllm-hust 2>/dev/null || command -v vllm 2>/dev/null || true)"
  fi
  if [[ -z "$VLLM_BIN" ]]; then
    echo "ERROR: neither requested vLLM binary nor vllm-hust/vllm found in container PATH" >&2
    exit 1
  fi
  echo "[container] using vLLM binary: $VLLM_BIN"
fi
echo "[container] python: $ENGINE_PYTHON"
echo "[container] vllm: $("$ENGINE_PYTHON" -c 'import vllm; print(vllm.__file__)' 2>/dev/null || echo 'N/A')"
echo "[container] vllm_ascend: $("$ENGINE_PYTHON" -c 'import vllm_ascend; print(vllm_ascend.__file__)' 2>/dev/null || echo 'N/A')"

if [[ -n "$VLLM_SCRIPT" ]]; then
  args=("$VLLM_BIN" "$VLLM_SCRIPT")
elif [[ -n "$ENGINE_PYTHON_OVERRIDE" ]]; then
  args=("$ENGINE_PYTHON" "$VLLM_BIN")
else
  args=("$VLLM_BIN")
fi
args+=(
  serve "__MODEL_PATH__"
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

if [[ "__ENABLE_PREFIX_CACHING__" == "1" ]]; then
  args+=(--enable-prefix-caching)
else
  args+=(--no-enable-prefix-caching)
fi
if [[ "__ENABLE_CHUNKED_PREFILL__" == "1" ]]; then
  args+=(--enable-chunked-prefill)
else
  args+=(--no-enable-chunked-prefill)
fi
[[ "__ENFORCE_EAGER__" == "1" ]] && args+=(--enforce-eager)
[[ "__EXPERT_PARALLEL__" == "1" ]] && args+=(--enable-expert-parallel)
[[ -n "__QUANTIZATION__" ]] && args+=(--quantization "__QUANTIZATION__")
[[ -n "${VLLM_ENGINE_COMPILATION_CONFIG:-}" ]] && args+=(--compilation-config "$VLLM_ENGINE_COMPILATION_CONFIG")
if [[ -n "${VLLM_ENGINE_EXTRA_ARGS_JSON:-}" ]]; then
  mapfile -t extra_args < <("$ENGINE_PYTHON" -S - <<'PY'
import json
import os
import sys

raw = os.environ.get("VLLM_ENGINE_EXTRA_ARGS_JSON", "")
try:
    args = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid VLLM_ENGINE_EXTRA_ARGS_JSON: {exc}") from exc
if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
    raise SystemExit("VLLM_ENGINE_EXTRA_ARGS_JSON must be a JSON list of strings")
for item in args:
    print(item)
PY
  )
  args+=("${extra_args[@]}")
fi

exec "${args[@]}"
BASH
)

replace() {
  local needle="$1"
  local value="$2"
  inner_script="${inner_script//"$needle"/"$value"}"
}

replace "__CONDA_ENV__" "$conda_env"
replace "__CONDA_PREFIX__" "$conda_prefix"
replace "__ENGINE_PYTHON__" "$engine_python"
replace "__EXTRA_ENV_EXPORTS__" "$extra_env_exports"
replace "__CONTAINER_LOG_FILE__" "$container_log_file"
replace "__TARGET_DEVICE__" "$target_device"
replace "__NPU_DEVICES__" "$runtime_visible_devices"
replace "__PLUGINS__" "$plugins"
replace "__FLASHCOMM1__" "$flashcomm1"
replace "__FUSED_MC2__" "$fused_mc2"
replace "__PYTHONPATH__" "$pythonpath"
replace "__CONTAINER_WORKSPACE_ROOT__" "$container_workspace_root"
replace "__VLLM_VERSION__" "$vllm_compat_version"
replace "__VLLM_BIN__" "$vllm_bin"
replace "__VLLM_SCRIPT__" "$vllm_script"
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
  --env "ASCEND_RT_VISIBLE_DEVICES=$runtime_visible_devices" \
  --env "ASCEND_VISIBLE_DEVICES=$runtime_visible_devices" \
  --env "VLLM_ENGINE_COMPILATION_CONFIG=$compilation_config" \
  --env "VLLM_ENGINE_EXTRA_ARGS_JSON=${VLLM_ENGINE_EXTRA_ARGS_JSON:-}" \
  --env "VLLM_USE_SIMPLE_KV_OFFLOAD=$simple_kv_offload" \
  "$container" bash "$container_script"
