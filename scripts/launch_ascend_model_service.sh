#!/usr/bin/env bash
# launch_ascend_model_service.sh — Start an Ascend NPU model service.
#
# ═══════════════════════════════════════════════════════════════════════════
#  Two launch modes — when to use which:
# ═══════════════════════════════════════════════════════════════════════════
#
#  1. Host mode (default, NO --docker flag)
#     ─────────────────────────────────────
#     Uses:  hust-ascend-manager launch
#     When:  Running vLLM directly on the host OS (bare-metal Ascend machine).
#            The host's CANN toolkit, torch_npu, and vllm-hust are all in the
#            SAME conda environment, so CANN versions are consistent.
#     Pros:  Automatic env setup (ASCEND_TOOLKIT_HOME, LD_LIBRARY_PATH, etc.),
#            CANN version auto-detection & matching via hust-ascend-manager.
#     Cons:  Requires hust-ascend-manager installed in the conda env.
#
#  2. Docker mode (--docker <container_name>)
#     ────────────────────────────────────────
#     Uses:  vllm-hust + vllm-ascend-hust via /workspace mount.
#     When:  Running inside a Docker container (e.g. quay.io/ascend/vllm-ascend).
#            The host's home dir is mounted at /workspace, and /workspace is in
#            Python's sys.path, so our forks (vllm-hust, vllm-ascend-hust) are
#            loaded automatically.  The _C_ascend C++ extension (.so compiled
#            inside the container) provides custom ops for the container's CANN.
#     Needs: CANN toolkit env sourced + LD_LIBRARY_PATH for libtorch.so/libtorch_npu.so.
#     Cons:  Do NOT activate host conda env (would introduce CANN mismatch).
#
# ═══════════════════════════════════════════════════════════════════════════
#
# Supports preset configurations for common models:
#   --preset w8a8        Qwen3-235B-A22B-W8A8 (quantized, auto-downloads from ModelScope)
#
# Usage:
#   # Docker mode (recommended for containerized environments)
#   bash scripts/launch_ascend_model_service.sh --preset w8a8 --docker my_container
#
#   # Host mode (recommended for bare-metal)
#   bash scripts/launch_ascend_model_service.sh --preset w8a8
#   bash scripts/launch_ascend_model_service.sh --preset w8a8 --download-model
#   bash scripts/launch_ascend_model_service.sh --model Qwen/Qwen2.5-7B-Instruct --tp 1
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# ── defaults ────────────────────────────────────────────────────────────────
CONDA_ENV="${CONDA_ENV:-vllm-hust-dev}"
MODEL_ID="${MODEL_ID:-Qwen/Qwen3-235B-A22B-Instruct-2507}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen3-235b-a22b-8npu}"
TP_SIZE="${TP_SIZE:-8}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-40960}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.9}"
DTYPE="${DTYPE:-bfloat16}"
LOAD_FORMAT="${LOAD_FORMAT:-auto}"
QUANTIZATION="${QUANTIZATION:-}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-4096}"
LOG_FILE="${LOG_FILE:-}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-1800}"
HEALTH_INTERVAL_SEC="${HEALTH_INTERVAL_SEC:-5}"
NO_HEALTH_CHECK=0
FOREGROUND=0
DRY_RUN=0
PRESET=""
DOWNLOAD_MODEL=0
SKIP_SETUP=0
DOCKER_CONTAINER=""

# ── model presets ────────────────────────────────────────────────────────────
# ModelScope model ID → local cache path mapping
declare -A PRESET_MODELSCOPE_ID=(
  [w8a8]="vllm-ascend/Qwen3-235B-A22B-W8A8"
)
declare -A PRESET_LOCAL_PATH=(
  [w8a8]="/data/shared_models/modelscope_cache/vllm-ascend/Qwen3-235B-A22B-W8A8"
)

apply_preset() {
  local preset="$1"
  case "$preset" in
    w8a8)
      # Only override if user hasn't explicitly set these
      [[ "$MODEL_ID" == "Qwen/Qwen3-235B-A22B-Instruct-2507" ]] && MODEL_ID="${PRESET_LOCAL_PATH[$preset]}"
      [[ -z "$QUANTIZATION" ]]    && QUANTIZATION="ascend"
      [[ "$MAX_MODEL_LEN" == "40960" ]] && MAX_MODEL_LEN="32768"
      # Reduce concurrency to free KV cache for longer context
      [[ "$MAX_NUM_SEQS" == "16" ]] && MAX_NUM_SEQS="2"
      # Ensure max_num_batched_tokens >= max_model_len
      if (( MAX_NUM_BATCHED_TOKENS < MAX_MODEL_LEN )); then
        MAX_NUM_BATCHED_TOKENS="$MAX_MODEL_LEN"
      fi
      [[ "$SERVED_MODEL_NAME" == "qwen3-235b-a22b-8npu" ]] && SERVED_MODEL_NAME="qwen3-235b-a22b-w8a8"
      ;;
    *)
      echo "Unknown preset: $preset" >&2
      echo "Available presets: ${!PRESET_MODELSCOPE_ID[*]}" >&2
      exit 1 ;;
  esac
  echo "[preset] applied '$preset': model=$MODEL_ID quantization=$QUANTIZATION max-model-len=$MAX_MODEL_LEN max-num-seqs=$MAX_NUM_SEQS"
}

download_model_from_modelscope() {
  local preset="$1"
  local ms_id="${PRESET_MODELSCOPE_ID[$preset]:-}"
  local local_path="${PRESET_LOCAL_PATH[$preset]:-}"

  if [[ -z "$ms_id" || -z "$local_path" ]]; then
    echo "[download] no ModelScope mapping for preset '$preset'" >&2
    return 1
  fi

  if [[ -d "$local_path" ]] && [[ "$(ls -A "$local_path"/*.safetensors 2>/dev/null | wc -l)" -gt 0 ]]; then
    echo "[download] model already present at $local_path"
    return 0
  fi

  local cache_dir="$(dirname "$(dirname "$local_path")")"
  echo "[download] downloading $ms_id from ModelScope → $cache_dir"
  echo "[download] this may take several hours for large models..."

  # Ensure modelscope is installed
  if ! /home/shuhao/miniconda3/envs/$CONDA_ENV/bin/python -c "import modelscope" 2>/dev/null; then
    echo "[download] installing modelscope in conda env $CONDA_ENV..."
    /home/shuhao/miniconda3/envs/$CONDA_ENV/bin/pip install -q modelscope
  fi

  # Ensure cache dir exists with correct permissions
  mkdir -p "$cache_dir" 2>/dev/null || sudo mkdir -p "$cache_dir" && sudo chown "$(whoami):$(id -gn)" "$cache_dir"

  TORCH_DEVICE_BACKEND_AUTOLOAD=0 /home/shuhao/miniconda3/envs/$CONDA_ENV/bin/python -c "
from modelscope import snapshot_download
p = snapshot_download('$ms_id', cache_dir='$cache_dir')
print('DOWNLOADED:', p)
" 2>&1 | tee /tmp/modelscope_download_${preset}.log

  if [[ -d "$local_path" ]]; then
    echo "[download] complete: $local_path"
  else
    echo "[download] ERROR: expected model at $local_path but not found" >&2
    return 1
  fi
}

# ── usage ────────────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
Usage: bash scripts/launch_ascend_model_service.sh [options]

Presets:
  --preset w8a8              Qwen3-235B-A22B-W8A8 (quantized, use with --download-model)

Options:
  Mode selection:
    --docker CONTAINER     Run inside Docker container (bypasses hust-ascend-manager)
                           Use this when running in containerized environments
                           to avoid CANN version mismatch between container runtime
                           and host-compiled torch_npu.
    --skip-setup           (Host mode only) Skip hust-ascend-manager env setup

  Environment:
    --env NAME             Conda env name (default: vllm-hust-dev)
    --model MODEL_ID       Model id/path (default: Qwen/Qwen3-235B-A22B-Instruct-2507)
    --host HOST            Bind host (default: 0.0.0.0)
    --port PORT            Bind port (default: 8000)
    --served-model-name NAME  Served model name (default: qwen3-235b-a22b-8npu)

  Model config:
    --tp SIZE              Tensor parallel size (default: 8)
    --max-model-len LEN    Max model length (default: 40960)
    --gpu-mem-util RATIO   GPU/NPU memory utilization (default: 0.9)
    --dtype DTYPE           Model dtype (default: bfloat16)
    --load-format FORMAT   Load format (default: auto)
    --quantization METHOD  Quantization method (e.g. ascend, for W8A8 models)
    --max-num-seqs N       Max concurrent sequences (default: 16)
    --max-num-batched-tokens N  Max batched tokens (default: 4096)

  Operational:
    --download-model       Download model from ModelScope before launching
    --log-file PATH        Log file path (default: auto in /tmp)
    --health-timeout SEC   Health check timeout seconds (default: 1800)
    --health-interval SEC  Health check interval seconds (default: 5)
    --no-health-check      Skip waiting for /health
    --foreground           Run command in foreground
    --dry-run              Print command only
    -h, --help             Show this help

Examples:
  # ── Docker mode (recommended for containerized environments) ──
  bash scripts/launch_ascend_model_service.sh --preset w8a8 --docker vllm_hust_ws_16rc

  # ── Host mode (recommended for bare-metal Ascend machines) ──
  bash scripts/launch_ascend_model_service.sh --preset w8a8
  bash scripts/launch_ascend_model_service.sh --preset w8a8 --download-model

  # Small model for testing
  bash scripts/launch_ascend_model_service.sh --model Qwen/Qwen2.5-7B-Instruct --tp 1 --port 8100

  # Dry run to inspect generated command
  bash scripts/launch_ascend_model_service.sh --preset w8a8 --docker my_container --dry-run
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      CONDA_ENV="$2"; shift 2 ;;
    --model)
      MODEL_ID="$2"; shift 2 ;;
    --host)
      HOST="$2"; shift 2 ;;
    --port)
      PORT="$2"; shift 2 ;;
    --served-model-name)
      SERVED_MODEL_NAME="$2"; shift 2 ;;
    --tp)
      TP_SIZE="$2"; shift 2 ;;
    --max-model-len)
      MAX_MODEL_LEN="$2"; shift 2 ;;
    --gpu-mem-util)
      GPU_MEM_UTIL="$2"; shift 2 ;;
    --dtype)
      DTYPE="$2"; shift 2 ;;
    --load-format)
      LOAD_FORMAT="$2"; shift 2 ;;
    --quantization)
      QUANTIZATION="$2"; shift 2 ;;
    --max-num-seqs)
      MAX_NUM_SEQS="$2"; shift 2 ;;
    --max-num-batched-tokens)
      MAX_NUM_BATCHED_TOKENS="$2"; shift 2 ;;
    --log-file)
      LOG_FILE="$2"; shift 2 ;;
    --health-timeout)
      HEALTH_TIMEOUT_SEC="$2"; shift 2 ;;
    --health-interval)
      HEALTH_INTERVAL_SEC="$2"; shift 2 ;;
    --no-health-check)
      NO_HEALTH_CHECK=1; shift ;;
    --foreground)
      FOREGROUND=1; shift ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --preset)
      PRESET="$2"; shift 2 ;;
    --download-model)
      DOWNLOAD_MODEL=1; shift ;;
    --skip-setup)
      SKIP_SETUP=1; shift ;;
    --docker)
      DOCKER_CONTAINER="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1 ;;
  esac
done

# ── apply preset (must happen before validation) ───────────────────────────
if [[ -n "$PRESET" ]]; then
  apply_preset "$PRESET"
fi

# ── download model if requested ──────────────────────────────────────────────
if (( DOWNLOAD_MODEL == 1 )); then
  if [[ -z "$PRESET" ]]; then
    echo "--download-model requires --preset (e.g. --preset w8a8)" >&2
    exit 1
  fi
  download_model_from_modelscope "$PRESET"
fi

if [[ -z "$LOG_FILE" ]]; then
  ts="$(date +%Y%m%d_%H%M%S)"
  LOG_FILE="/tmp/qwen_launch_${ts}.log"
fi

if [[ -z "$DOCKER_CONTAINER" ]] && ! command -v conda >/dev/null 2>&1; then
  echo "conda not found in PATH" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found in PATH" >&2
  exit 1
fi

resolve_conda_profile() {
  local conda_base=""

  if [[ -n "${CONDA_EXE:-}" ]]; then
    conda_base="$(cd -- "$(dirname -- "${CONDA_EXE}")/.." && pwd)"
  else
    conda_base="$(conda info --base 2>/dev/null || true)"
  fi

  if [[ -z "$conda_base" ]]; then
    return 1
  fi

  local conda_profile="$conda_base/etc/profile.d/conda.sh"
  if [[ ! -f "$conda_profile" ]]; then
    return 1
  fi

  printf '%s\n' "$conda_profile"
}

read -r -d '' LAUNCH_INNER <<'EOF' || true
set -euo pipefail
cd "__REPO_DIR__"
if ! command -v hust-ascend-manager >/dev/null 2>&1; then
  echo "hust-ascend-manager is not available in current conda env" >&2
  exit 1
fi
exec hust-ascend-manager launch "__MODEL_ID__" \
  __SKIP_SETUP_ARG__ \
  --host "__HOST__" \
  --port "__PORT__" \
  --served-model-name "__SERVED_MODEL_NAME__" \
  -- \
  --tensor-parallel-size "__TP_SIZE__" \
  --max-model-len "__MAX_MODEL_LEN__" \
  --gpu-memory-utilization "__GPU_MEM_UTIL__" \
  --dtype "__DTYPE__" \
  --load-format "__LOAD_FORMAT__" \
  --enable-expert-parallel \
  --max-num-seqs "__MAX_NUM_SEQS__" \
  --max-num-batched-tokens "__MAX_NUM_BATCHED_TOKENS__" \
  __QUANTIZATION_ARG__
EOF

# ── Docker mode template: use vllm-hust via /workspace mount ────────────────
# Key insight: The host's entire home directory is mounted at /workspace inside
# the container, and /workspace is in Python's sys.path.  This means:
#   - vllm resolves to /workspace/vllm-hust/vllm (our custom fork)
#   - vllm_ascend resolves to /workspace/vllm-ascend-hust/vllm_ascend (our fork)
#   - _C_ascend.so (compiled for container's CANN) is loaded automatically
#
# Requirements:
#   1. Source CANN toolkit env (set_env.sh) for libascendcl.so etc.
#   2. LD_LIBRARY_PATH must include torch/lib and torch_npu/lib for .so deps
#   3. Do NOT activate host conda env (would introduce CANN version mismatch)
read -r -d '' DOCKER_INNER <<'EOF' || true
set -euo pipefail

# NPU device selection
NPU_DEVICES="__NPU_DEVICES__"
export ASCEND_RT_VISIBLE_DEVICES="$NPU_DEVICES"
export ASCEND_VISIBLE_DEVICES="$NPU_DEVICES"
export HCCL_OP_EXPANSION_MODE=AIV
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True

# Source CANN toolkit environment (provides libascendcl.so, libascendalog.so, etc.)
if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi

# Add torch/torch_npu lib dirs so _C_ascend.so can find libtorch.so & libtorch_npu.so
_TORCH_LIB="$(python3 -c 'import torch, os; print(os.path.join(os.path.dirname(torch.__file__), "lib"))' 2>/dev/null || true)"
_TORCH_NPU_LIB="$(python3 -c 'import torch_npu, os; print(os.path.join(os.path.dirname(torch_npu.__file__), "lib"))' 2>/dev/null || true)"
export LD_LIBRARY_PATH="${_TORCH_LIB:-}:${_TORCH_NPU_LIB:-}:${LD_LIBRARY_PATH:-}"

# vLLM plugin & offline flags
export VLLM_PLUGINS="${VLLM_PLUGINS:-ascend}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
# Disable preflight (NPU first-init is slow, causes 20s timeout)
export VLLM_ASCEND_TORCH_PREFLIGHT="${VLLM_ASCEND_TORCH_PREFLIGHT:-0}"
# Disable custom C++ ops: CANN 8.5.1 for 910B lacks AddRmsNormBias in its op registry,
# causing SDMA crashes when _C_ascend custom ops are active.  Falls back to torch_npu
# hardware-accelerated ops (npu_add_rms_norm etc.) which are fully supported.
export COMPILE_CUSTOM_KERNELS="${COMPILE_CUSTOM_KERNELS:-0}"

# Ascend MoE performance optimizations (910B / A2)
# FlashComm1: optimize TP all-reduce communication for high concurrency
export VLLM_ASCEND_ENABLE_FLASHCOMM1="${VLLM_ASCEND_ENABLE_FLASHCOMM1:-1}"

# Source ATB env if available
if [[ -n "${HUST_ATB_SET_ENV:-}" && -f "${HUST_ATB_SET_ENV}" ]]; then
  set +u; source "${HUST_ATB_SET_ENV}" --cxx_abi=1; set -u
fi

# Isolate cache
export HOME=/tmp/vllm-hust-home
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export VLLM_CACHE_ROOT="$HOME/.cache/vllm"
export VLLM_CONFIG_ROOT="$HOME/.config/vllm"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" \
         "$VLLM_CACHE_ROOT" "$VLLM_CONFIG_ROOT"

# Resolve vllm binary (vllm-hust preferred, fall back to vllm)
VLLM_BIN="$(command -v vllm-hust 2>/dev/null || command -v vllm 2>/dev/null || echo '')"
if [[ -z "$VLLM_BIN" ]]; then
  echo "ERROR: neither vllm-hust nor vllm found in container PATH" >&2
  exit 1
fi
echo "[docker-inner] using vllm binary: $VLLM_BIN"
echo "[docker-inner] python: $(which python3)"
echo "[docker-inner] vllm: $(python3 -c 'import vllm; print(vllm.__file__)' 2>/dev/null || echo 'N/A')"
echo "[docker-inner] vllm_ascend: $(python3 -c 'import vllm_ascend; print(vllm_ascend.__file__)' 2>/dev/null || echo 'N/A')"
echo "[docker-inner] _C_ascend: $(python3 -c 'import vllm_ascend.vllm_ascend_C; print(vllm_ascend.vllm_ascend_C.__file__)' 2>/dev/null || echo 'N/A')"

exec "$VLLM_BIN" serve \
  "__MODEL_ID__" \
  --served-model-name "__SERVED_MODEL_NAME__" \
  --host "__HOST__" --port "__PORT__" \
  --tensor-parallel-size "__TP_SIZE__" \
  --max-model-len "__MAX_MODEL_LEN__" \
  --max-num-batched-tokens "__MAX_NUM_BATCHED_TOKENS__" \
  --gpu-memory-utilization "__GPU_MEM_UTIL__" \
  --dtype "__DTYPE__" \
  --load-format "__LOAD_FORMAT__" \
  --enable-expert-parallel \
  --trust-remote-code \
  --max-num-seqs "__MAX_NUM_SEQS__" \
  __QUANTIZATION_ARG__
EOF

# ── Select template based on mode ──────────────────────────────────────────
if [[ -n "$DOCKER_CONTAINER" ]]; then
  # Docker mode: use vllm-hust via /workspace mount (avoids CANN version mismatch)
  ACTIVE_INNER="$DOCKER_INNER"
  # Determine NPU devices from TP_SIZE
  if (( TP_SIZE > 1 )); then
    NPU_DEVICES=$(seq -s, 0 $((TP_SIZE - 1)))
  else
    NPU_DEVICES="0"
  fi
  ACTIVE_INNER="${ACTIVE_INNER//__NPU_DEVICES__/$NPU_DEVICES}"
else
  # Host mode: use hust-ascend-manager launch
  ACTIVE_INNER="$LAUNCH_INNER"
fi

ACTIVE_INNER="${ACTIVE_INNER//__REPO_DIR__/$REPO_DIR}"
ACTIVE_INNER="${ACTIVE_INNER//__MODEL_ID__/$MODEL_ID}"
ACTIVE_INNER="${ACTIVE_INNER//__HOST__/$HOST}"
ACTIVE_INNER="${ACTIVE_INNER//__PORT__/$PORT}"
ACTIVE_INNER="${ACTIVE_INNER//__SERVED_MODEL_NAME__/$SERVED_MODEL_NAME}"
ACTIVE_INNER="${ACTIVE_INNER//__TP_SIZE__/$TP_SIZE}"
ACTIVE_INNER="${ACTIVE_INNER//__MAX_MODEL_LEN__/$MAX_MODEL_LEN}"
ACTIVE_INNER="${ACTIVE_INNER//__GPU_MEM_UTIL__/$GPU_MEM_UTIL}"
ACTIVE_INNER="${ACTIVE_INNER//__DTYPE__/$DTYPE}"
ACTIVE_INNER="${ACTIVE_INNER//__LOAD_FORMAT__/$LOAD_FORMAT}"
ACTIVE_INNER="${ACTIVE_INNER//__MAX_NUM_SEQS__/$MAX_NUM_SEQS}"
ACTIVE_INNER="${ACTIVE_INNER//__MAX_NUM_BATCHED_TOKENS__/$MAX_NUM_BATCHED_TOKENS}"

# Conditionally add --quantization
if [[ -n "$QUANTIZATION" ]]; then
  ACTIVE_INNER="${ACTIVE_INNER//__QUANTIZATION_ARG__/--quantization \"$QUANTIZATION\"}"
else
  ACTIVE_INNER="${ACTIVE_INNER//__QUANTIZATION_ARG__/}"
fi

# Conditionally add --skip-setup (host mode only)
if (( SKIP_SETUP == 1 )); then
  ACTIVE_INNER="${ACTIVE_INNER//__SKIP_SETUP_ARG__/--skip-setup}"
else
  ACTIVE_INNER="${ACTIVE_INNER//__SKIP_SETUP_ARG__/}"
fi

# ── Build full command ──────────────────────────────────────────────────────
if [[ -n "$DOCKER_CONTAINER" ]]; then
  # Docker mode: conda is already activated inside container, just run inner
  FULL_CMD="$ACTIVE_INNER"
else
  # Host mode: activate conda then run inner
  CONDA_PROFILE="$(resolve_conda_profile || true)"
  if [[ -z "$CONDA_PROFILE" ]]; then
    echo "Unable to resolve conda profile script (expected <conda_base>/etc/profile.d/conda.sh)" >&2
    exit 1
  fi
  FULL_CMD="source \"$CONDA_PROFILE\" && conda activate \"$CONDA_ENV\" && ${ACTIVE_INNER}"
fi

if [[ -n "$DOCKER_CONTAINER" ]]; then
  echo "[launch] MODE: Docker (vllm-hust via /workspace mount)"
  echo "[launch] docker container: $DOCKER_CONTAINER"
  echo "[launch] vllm-hust + vllm-ascend-hust loaded via /workspace → host home mount"
else
  echo "[launch] MODE: Host (via hust-ascend-manager launch)"
fi
echo "[launch] conda env: $CONDA_ENV"
echo "[launch] model: $MODEL_ID"
echo "[launch] target: http://127.0.0.1:$PORT"
echo "[launch] log file: $LOG_FILE"

if (( DRY_RUN == 1 )); then
  echo "[launch] dry run command:"
  echo "$FULL_CMD"
  exit 0
fi

# ── Docker mode: write temp script and exec via docker ─────────────────────
if [[ -n "$DOCKER_CONTAINER" ]]; then
  # Ensure /home/shuhao → /workspace symlink in container (for conda shebang resolution)
  sudo docker exec "$DOCKER_CONTAINER" bash -c "mkdir -p /home && ln -sf /workspace /home/shuhao" 2>/dev/null || true

  TEMP_SCRIPT="/tmp/vllm_launch_$$.sh"
  # Convert host paths to container paths (/home/shuhao → /workspace)
  CONTAINER_CMD="${FULL_CMD//\/home\/shuhao\//\/workspace/}"
  printf '#!/usr/bin/env bash\nset -euo pipefail\n%s\n' "$CONTAINER_CMD" > "$TEMP_SCRIPT"
  chmod +x "$TEMP_SCRIPT"
  # Copy script into mounted area so container can access it
  HOST_SCRIPT="/home/shuhao/.cache/vllm_launch_$$.sh"
  mkdir -p "$(dirname "$HOST_SCRIPT")"
  cp "$TEMP_SCRIPT" "$HOST_SCRIPT"
  chmod +x "$HOST_SCRIPT"
  CONTAINER_SCRIPT="${HOST_SCRIPT//\/home\/shuhao\//\/workspace/}"

  if (( FOREGROUND == 1 )); then
    sudo docker exec "$DOCKER_CONTAINER" bash "$CONTAINER_SCRIPT"
    RC=$?
    rm -f "$TEMP_SCRIPT" "$HOST_SCRIPT"
    exit $RC
  fi

  echo "[launch] docker container: $DOCKER_CONTAINER"
  nohup sudo docker exec "$DOCKER_CONTAINER" bash "$CONTAINER_SCRIPT" >"$LOG_FILE" 2>&1 &
  PID="$!"
  echo "[launch] started pid: $PID (docker exec)"
  rm -f "$TEMP_SCRIPT"
else
  # ── Host mode: run directly ───────────────────────────────────────────────
  if (( FOREGROUND == 1 )); then
    eval "$FULL_CMD"
    exit $?
  fi

  nohup bash -lc "$FULL_CMD" >"$LOG_FILE" 2>&1 &
  PID="$!"
  echo "[launch] started pid: $PID"
fi

if (( NO_HEALTH_CHECK == 1 )); then
  echo "[launch] skip health check"
  exit 0
fi

start_ts="$(date +%s)"
while true; do
  if curl -fsS -m 5 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "[launch] health check passed"
    echo "[launch] models endpoint:"
    curl -fsS -m 8 "http://127.0.0.1:${PORT}/v1/models" || true
    echo
    exit 0
  fi

  if ! kill -0 "$PID" >/dev/null 2>&1; then
    echo "[launch] process exited before health became ready" >&2
    tail -n 120 "$LOG_FILE" || true
    exit 1
  fi

  now_ts="$(date +%s)"
  elapsed="$((now_ts - start_ts))"
  if (( elapsed >= HEALTH_TIMEOUT_SEC )); then
    echo "[launch] health check timeout after ${HEALTH_TIMEOUT_SEC}s" >&2
    tail -n 120 "$LOG_FILE" || true
    exit 1
  fi

  sleep "$HEALTH_INTERVAL_SEC"
done
