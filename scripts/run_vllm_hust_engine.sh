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
    [[ -z "$key" ]] && continue
    [[ -v "$key" ]] && continue
    export "$line"
  done < "$env_file"
}

load_dotenv "$repo_root/.env"

container="${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-vllm-ascend-dev}}"
container_image="${VLLM_ENGINE_IMAGE:-${IMAGE:-quay.io/ascend/vllm-ascend:v0.21.0rc1-openeuler}}"
auto_create_container="${VLLM_ENGINE_AUTO_CREATE_CONTAINER:-true}"
container_non_interactive="${VLLM_ENGINE_CONTAINER_NON_INTERACTIVE:-1}"
recreate_container="${VLLM_ENGINE_RECREATE_CONTAINER:-false}"
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
compilation_config="${VLLM_ENGINE_COMPILATION_CONFIG:-}"
vllm_bin="${VLLM_ENGINE_BIN:-vllm-hust}"
vllm_script="${VLLM_ENGINE_SCRIPT:-}"
conda_prefix="${VLLM_ENGINE_CONDA_PREFIX:-}"
conda_env="${VLLM_ENGINE_CONDA_ENV:-${CONDA_ENV:-vllm-hust-dev}}"
engine_python="${VLLM_ENGINE_PYTHON:-}"
pip_install="${VLLM_ENGINE_PIP_INSTALL:-}"
import_preflight="${VLLM_ENGINE_IMPORT_PREFLIGHT:-}"
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
host_log_file="${VLLM_ENGINE_HOST_LOG_FILE:-}"
lifecycle_diagnostics_file="${VLLM_ENGINE_LIFECYCLE_DIAGNOSTICS_FILE:-}"
require_explicit_device_security="${VLLM_ENGINE_REQUIRE_EXPLICIT_DEVICE_SECURITY:-0}"
container_security_profile="${VLLM_ENGINE_CONTAINER_SECURITY_PROFILE:-}"
ascend_manager_expected_commit="${VLLM_ENGINE_ASCEND_MANAGER_EXPECTED_COMMIT:-}"
ascend_manager_python="${VLLM_ENGINE_ASCEND_MANAGER_PYTHON:-}"
ascend_manager_provenance_receipt="${VLLM_ENGINE_ASCEND_MANAGER_PROVENANCE_RECEIPT:-}"
ascend_manager_device_discovery_root="${VLLM_ENGINE_ASCEND_MANAGER_DEVICE_DISCOVERY_ROOT:-}"
run_root_host="${VLLM_ENGINE_RUN_ROOT_HOST:-}"
run_root_parent="${VLLM_ENGINE_RUN_ROOT_PARENT:-}"
run_root_container="${VLLM_ENGINE_RUN_ROOT_CONTAINER:-}"
run_root_uid="${VLLM_ENGINE_RUN_ROOT_UID:-}"
run_root_gid="${VLLM_ENGINE_RUN_ROOT_GID:-}"
optimization_repo_host="${VLLM_ENGINE_OPTIMIZATION_REPO_HOST:-}"
optimization_src_host="${VLLM_ENGINE_OPTIMIZATION_SRC_HOST:-}"
optimization_src_container="${VLLM_ENGINE_OPTIMIZATION_SRC_CONTAINER:-}"
optimization_import_module="${VLLM_ENGINE_OPTIMIZATION_IMPORT_MODULE:-}"

# Preserve launcher, bootstrap, docker-exec, and engine stderr even when the
# generated in-container script never starts. The container-side log below is
# necessarily too late to observe a failed docker exec boundary.
if [[ -n "$host_log_file" ]]; then
  if [[ "$host_log_file" != /* ]]; then
    echo "ERROR: VLLM_ENGINE_HOST_LOG_FILE must be absolute." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$host_log_file")"
  if [[ -L "$host_log_file" ]]; then
    echo "ERROR: refusing symlink host engine log: $host_log_file" >&2
    exit 1
  fi
  : >> "$host_log_file"
  if [[ ! -f "$host_log_file" || "$(stat -c '%h' "$host_log_file")" != "1" ]]; then
    echo "ERROR: host engine log must be a regular single-link file." >&2
    exit 1
  fi
  chmod 600 "$host_log_file"
  exec > >(sed -u -E 's/sk-[A-Za-z0-9._-]+/<redacted>/g; s/(api-key[ =])[^ ]+/\1<redacted>/Ig; s/(Bearer )[A-Za-z0-9._~+\/-]+/\1<redacted>/g; s/([A-Za-z_]*(KEY|TOKEN|SECRET)[A-Za-z_]*=)[^ ]+/\1<redacted>/g' | tee -a "$host_log_file") 2>&1
fi

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

keys = []
for key in os.environ:
    upper = key.upper()
    # Preserve the explicit forwarding allowlist control variable. Actual
    # credential-like variables remain filtered below unless they are handled
    # through a dedicated redacted path.
    if key != "VLLM_ENGINE_EXTRA_ENV_KEYS" and (
        "KEY" in upper or "TOKEN" in upper or "SECRET" in upper
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
if [[ "$require_explicit_device_security" == "1" ]]; then
  if [[ "$container_security_profile" != "explicit-devices-nonprivileged-v1" ]]; then
    echo "ERROR: exact-device launch requires explicit-devices-nonprivileged-v1." >&2
    exit 1
  fi
  if [[ ! "$ascend_manager_expected_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: exact-device launch requires a pinned ascend-runtime-manager commit." >&2
    exit 1
  fi
  if [[ -z "$ascend_manager_python" || "$ascend_manager_python" != /* || ! -x "$ascend_manager_python" ]]; then
    echo "ERROR: exact-device launch requires an absolute executable manager Python." >&2
    exit 1
  fi
fi
run_bind_enabled=0
manager_extra_bind=""
manager_runtime_bind=""
if [[ -n "$run_root_host$run_root_parent$run_root_container$run_root_uid$run_root_gid" ]]; then
  if [[ -z "$run_root_host" || -z "$run_root_parent" || -z "$run_root_container" || -z "$run_root_uid" || -z "$run_root_gid" ]]; then
    echo "ERROR: exact-run bind requires host root, parent, container root, UID, and GID." >&2
    exit 1
  fi
  if [[ "$run_root_host" != /* || "$run_root_parent" != /* || "$run_root_container" != /run/kvdelta/* ]]; then
    echo "ERROR: exact-run bind paths must be absolute and use /run/kvdelta/<namespace>." >&2
    exit 1
  fi
  if [[ ! "$run_root_uid" =~ ^[0-9]+$ || ! "$run_root_gid" =~ ^[0-9]+$ ]]; then
    echo "ERROR: exact-run bind UID/GID must be numeric." >&2
    exit 1
  fi
  if [[ -L "$run_root_host" || ! -d "$run_root_host" || -L "$run_root_parent" || ! -d "$run_root_parent" ]]; then
    echo "ERROR: exact-run bind source and parent must be existing non-symlink directories." >&2
    exit 1
  fi
  canonical_run_root="$(readlink -f "$run_root_host")"
  canonical_run_parent="$(readlink -f "$run_root_parent")"
  if [[ "$canonical_run_root" != "$run_root_host" || "$canonical_run_parent" != "$run_root_parent" || "$run_root_host" != "$run_root_parent/"* ]]; then
    echo "ERROR: exact-run bind source must be canonical and contained by its frozen parent." >&2
    exit 1
  fi
  run_root_stat="$(stat -c '%u:%g:%a' "$run_root_host")"
  if [[ "$run_root_stat" != "$run_root_uid:$run_root_gid:770" ]]; then
    echo "ERROR: exact-run bind source must match frozen UID:GID and mode 0770." >&2
    exit 1
  fi
  run_bind_enabled=1
  manager_extra_bind="$run_root_host:$run_root_container"
fi
if [[ -n "$lifecycle_diagnostics_file" ]]; then
  if [[ "$run_bind_enabled" != "1" ]]; then
    echo "ERROR: lifecycle diagnostics require the exact-run bind identity." >&2
    exit 1
  fi
  if [[ "$lifecycle_diagnostics_file" != "$run_root_host/container-lifecycle-diagnostics.jsonl" ]]; then
    echo "ERROR: lifecycle diagnostics must use the frozen exact-run path." >&2
    exit 1
  fi
  if [[ -e "$lifecycle_diagnostics_file" || -L "$lifecycle_diagnostics_file" ]]; then
    echo "ERROR: refusing pre-existing lifecycle diagnostics file." >&2
    exit 1
  fi
  umask 077
  : > "$lifecycle_diagnostics_file"
  if [[ ! -f "$lifecycle_diagnostics_file" || "$(stat -c '%h' "$lifecycle_diagnostics_file")" != "1" ]]; then
    echo "ERROR: lifecycle diagnostics must be a regular single-link file." >&2
    exit 1
  fi
  chmod 600 "$lifecycle_diagnostics_file"
fi
optimization_bind_enabled=0
manager_optimization_bind=""
if [[ -n "$optimization_repo_host$optimization_src_host$optimization_src_container$optimization_import_module" ]]; then
  if [[ "$run_bind_enabled" != "1" ]]; then
    echo "ERROR: optimization source bind requires the exact-run bind identity." >&2
    exit 1
  fi
  if [[ -z "$optimization_repo_host" || -z "$optimization_src_host" || -z "$optimization_src_container" || -z "$optimization_import_module" ]]; then
    echo "ERROR: optimization source bind requires repo root, source root, container root, and import module." >&2
    exit 1
  fi
  if [[ "$optimization_repo_host" != /* || "$optimization_src_host" != /* || "$optimization_src_container" != /opt/vllm-optimization/*/src ]]; then
    echo "ERROR: optimization source bind paths must be absolute and use /opt/vllm-optimization/<namespace>/src." >&2
    exit 1
  fi
  if [[ -L "$optimization_repo_host" || ! -d "$optimization_repo_host" || -L "$optimization_src_host" || ! -d "$optimization_src_host" ]]; then
    echo "ERROR: optimization repo and source must be existing non-symlink directories." >&2
    exit 1
  fi
  canonical_optimization_repo="$(readlink -f "$optimization_repo_host")"
  canonical_optimization_src="$(readlink -f "$optimization_src_host")"
  if [[ "$canonical_optimization_repo" != "$optimization_repo_host" || "$canonical_optimization_src" != "$optimization_src_host" || "$optimization_src_host" != "$optimization_repo_host/"* ]]; then
    echo "ERROR: optimization source must be canonical and contained by its frozen repo root." >&2
    exit 1
  fi
  if [[ ! "$optimization_import_module" =~ ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$ ]]; then
    echo "ERROR: optimization import module is malformed." >&2
    exit 1
  fi
  optimization_module_file="$optimization_src_host/${optimization_import_module//.//}.py"
  if [[ -L "$optimization_module_file" || ! -f "$optimization_module_file" || ! -r "$optimization_module_file" ]]; then
    echo "ERROR: optimization import module source is absent, symlinked, or unreadable." >&2
    exit 1
  fi
  optimization_bind_enabled=1
  manager_optimization_bind="$optimization_src_host:$optimization_src_container"
fi
if [[ "$run_bind_enabled" == "1" ]]; then
  runtime_carrier_source="$repo_root/scripts/ascend-container-runtime.sh"
  runtime_carrier_stager="$repo_root/scripts/stage_container_runtime.py"
  if [[ ! -f "$runtime_carrier_stager" || -L "$runtime_carrier_stager" ]]; then
    echo "ERROR: container runtime carrier stager is absent or symlinked." >&2
    exit 1
  fi
  runtime_carrier_python="${ascend_manager_python:-python3}"
  "$runtime_carrier_python" "$runtime_carrier_stager" \
    --source "$runtime_carrier_source" \
    --run-root "$run_root_host" \
    --expected-run-root "$canonical_run_root"
  runtime_carrier_host="$run_root_host/container-runtime-carrier"
  runtime_carrier_receipt="$run_root_host/container-runtime-carrier-receipt.json"
  if [[ "$(stat -c '%a' "$runtime_carrier_host")" != "555" || \
        "$(stat -c '%a' "$runtime_carrier_host/scripts")" != "555" || \
        "$(stat -c '%a' "$runtime_carrier_host/scripts/ascend-container-runtime.sh")" != "555" || \
        "$(stat -c '%a' "$runtime_carrier_receipt")" != "600" ]]; then
    echo "ERROR: staged container runtime carrier modes drifted." >&2
    exit 1
  fi
  if ! cmp -s "$runtime_carrier_source" "$runtime_carrier_host/scripts/ascend-container-runtime.sh"; then
    echo "ERROR: staged container runtime carrier bytes drifted." >&2
    exit 1
  fi
  manager_runtime_bind="$runtime_carrier_host:/workspace/vllm-hust-dev-hub"
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
  HUST_ASCEND_MANAGER_VISIBLE_DEVICES="$npu_devices" \
  HUST_ASCEND_MANAGER_CONTAINER_SECURITY_PROFILE="$container_security_profile" \
  HUST_ASCEND_MANAGER_EXPECTED_COMMIT="$ascend_manager_expected_commit" \
  HUST_ASCEND_MANAGER_PYTHON="$ascend_manager_python" \
  HUST_ASCEND_MANAGER_PROVENANCE_RECEIPT="$ascend_manager_provenance_receipt" \
  HUST_ASCEND_MANAGER_DEVICE_DISCOVERY_ROOT="$ascend_manager_device_discovery_root" \
  VLLM_HUST_ASCEND_EXTRA_BIND_MOUNT="$manager_extra_bind" \
  VLLM_HUST_ASCEND_RUNTIME_BIND_MOUNT="$manager_runtime_bind" \
  VLLM_HUST_ASCEND_OPTIMIZATION_BIND_MOUNT="$manager_optimization_bind" \
  VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE="$container_non_interactive" \
    "$repo_root/scripts/ascend-official-container.sh" start

  if ! container_is_running; then
    echo "ERROR: Docker container '$container' is still not running after bootstrap." >&2
    exit 1
  fi
}

ensure_container_ready

container_full_id=""
container_started_at=""
container_pid1=""
container_runtime_log_file=""
capture_pid_identity() {
  local phase="$1"
  local pid="$2"
  [[ -n "$lifecycle_diagnostics_file" ]] || return 0
  python3 - "$phase" "$pid" >> "$lifecycle_diagnostics_file" <<'PY'
import json
import os
from pathlib import Path
import sys

phase, pid_text = sys.argv[1:]
payload = {"kind": "host-pid-identity", "phase": phase, "pid": int(pid_text or "0")}
if not pid_text.isdigit() or int(pid_text) <= 0:
    payload["status"] = "ABSENT"
else:
    pid = int(pid_text)
    proc = Path("/proc") / str(pid)
    try:
        stat_text = (proc / "stat").read_text(encoding="utf-8")
        close = stat_text.rfind(")")
        fields = stat_text[close + 2:].split()
        payload.update({
            "status": "PASS",
            "comm": stat_text[stat_text.find("(") + 1:close],
            "state": fields[0],
            "ppid": int(fields[1]),
            "starttime": int(fields[19]),
            "cgroup": (proc / "cgroup").read_text(encoding="utf-8", errors="replace").splitlines(),
            "exe": os.readlink(proc / "exe"),
            "cmdline_length": len((proc / "cmdline").read_bytes()),
        })
    except OSError as exc:
        payload.update({
            "status": "UNAVAILABLE",
            "error_type": type(exc).__name__,
            "errno": exc.errno,
        })
print(json.dumps(payload, sort_keys=True))
PY
}
capture_container_inspect() {
  local phase="$1"
  [[ -n "$lifecycle_diagnostics_file" ]] || return 0
  if ! "${docker_cmd[@]}" inspect --format \
      '{"kind":"container-inspect","phase":"'"$phase"'","container_id":{{json .Id}},"name":{{json .Name}},"state":{{json .State}},"restart_count":{{json .RestartCount}},"config_user":{{json .Config.User}},"host_config":{"memory":{{json .HostConfig.Memory}},"memory_swap":{{json .HostConfig.MemorySwap}},"oom_kill_disable":{{json .HostConfig.OomKillDisable}},"pids_limit":{{json .HostConfig.PidsLimit}},"runtime":{{json .HostConfig.Runtime}},"pid_mode":{{json .HostConfig.PidMode}},"security_opt":{{json .HostConfig.SecurityOpt}}}}' \
      "$container" >> "$lifecycle_diagnostics_file"; then
    printf '{"kind":"container-inspect","phase":"%s","status":"UNAVAILABLE"}\n' \
      "$phase" >> "$lifecycle_diagnostics_file"
    return 1
  fi
}
capture_container_runtime_logs() {
  local event_until="$1"
  [[ -n "$lifecycle_diagnostics_file" ]] || return 0
  container_runtime_log_file="$run_root_host/container-runtime.log"
  local tmp_runtime_log="$container_runtime_log_file.tmp.$$"
  if [[ -e "$container_runtime_log_file" || -L "$container_runtime_log_file" ]]; then
    printf '%s\n' '{"kind":"container-runtime-log","status":"UNAVAILABLE_PREEXISTING"}' \
      >> "$lifecycle_diagnostics_file"
    return 1
  fi
  umask 077
  if ! timeout 10 "${docker_cmd[@]}" logs --timestamps \
      --since "$container_started_at" --until "$event_until" "$container" 2>&1 \
      | sed -u -E 's/sk-[A-Za-z0-9._-]+/<redacted>/g; s/(api-key[ =])[^ ]+/\1<redacted>/Ig; s/(Bearer )[A-Za-z0-9._~+\/-]+/\1<redacted>/g; s/([A-Za-z_]*(KEY|TOKEN|SECRET)[A-Za-z_]*=)[^ ]+/\1<redacted>/g' \
      > "$tmp_runtime_log"; then
    rm -f "$tmp_runtime_log"
    printf '%s\n' '{"kind":"container-runtime-log","status":"UNAVAILABLE_CAPTURE_FAILED"}' \
      >> "$lifecycle_diagnostics_file"
    return 1
  fi
  chmod 600 "$tmp_runtime_log"
  if [[ ! -f "$tmp_runtime_log" || -L "$tmp_runtime_log" || "$(stat -c '%h' "$tmp_runtime_log")" != "1" ]]; then
    rm -f "$tmp_runtime_log"
    printf '%s\n' '{"kind":"container-runtime-log","status":"UNAVAILABLE_UNSAFE_FILE"}' \
      >> "$lifecycle_diagnostics_file"
    return 1
  fi
  mv "$tmp_runtime_log" "$container_runtime_log_file"
  python3 - "$container_runtime_log_file" "$event_until" \
      >> "$lifecycle_diagnostics_file" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
print(json.dumps({
    "kind": "container-runtime-log",
    "status": "PASS",
    "path": str(path),
    "bytes": path.stat().st_size,
    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "capture_until": sys.argv[2],
}, sort_keys=True))
PY
}
capture_docker_events() {
  local event_until="$1"
  [[ -n "$lifecycle_diagnostics_file" ]] || return 0
  if [[ -z "$container_full_id" || -z "$container_started_at" ]]; then
    printf '%s\n' '{"kind":"docker-events","status":"UNAVAILABLE_NO_START_BINDING"}' \
      >> "$lifecycle_diagnostics_file"
    return 1
  fi
  if ! timeout 10 "${docker_cmd[@]}" events \
      --since "$container_started_at" --until "$event_until" \
      --filter "container=$container_full_id" --format '{{json .}}' \
      | head -200 \
      | python3 -c '
import json
import sys
event_until = sys.argv[1]
terminal_actions = {"die", "kill", "stop", "destroy"}
terminal_seen = False
for line in sys.stdin:
    line = line.strip()
    if line:
        source = json.loads(line)
        attributes = source.get("Actor", {}).get("Attributes", {})
        event = {
            key: source[key]
            for key in ("Type", "Action", "status", "id", "time", "timeNano")
            if key in source
        }
        for key in ("exitCode", "execID", "signal", "execDuration"):
            if key in attributes:
                event[key] = attributes[key]
        event["capture_until"] = event_until
        action = source.get("Action") or source.get("status") or ""
        terminal_seen = terminal_seen or action in terminal_actions
        print(json.dumps({"kind": "docker-event", "event": event}, sort_keys=True))
if not terminal_seen:
    print(json.dumps({
        "kind": "docker-events",
        "status": "UNAVAILABLE_NO_TERMINAL_EVENT",
        "capture_until": event_until,
    }, sort_keys=True))
    raise SystemExit(3)
' "$event_until" >> "$lifecycle_diagnostics_file"; then
    printf '%s\n' '{"kind":"docker-events","status":"UNAVAILABLE"}' \
      >> "$lifecycle_diagnostics_file"
    return 1
  fi
}

if [[ -n "$lifecycle_diagnostics_file" ]]; then
  container_full_id="$("${docker_cmd[@]}" inspect --format '{{.Id}}' "$container")"
  container_started_at="$("${docker_cmd[@]}" inspect --format '{{.State.StartedAt}}' "$container")"
  container_pid1="$("${docker_cmd[@]}" inspect --format '{{.State.Pid}}' "$container")"
  if [[ ! "$container_full_id" =~ ^[0-9a-f]{64}$ || -z "$container_started_at" || ! "$container_pid1" =~ ^[0-9]+$ ]]; then
    echo "ERROR: lifecycle diagnostics could not bind immutable container start identity." >&2
    exit 1
  fi
  capture_container_inspect "start"
  capture_pid_identity "start" "$container_pid1"
fi

if [[ "$run_bind_enabled" == "1" ]]; then
  observed_run_mount="$("${docker_cmd[@]}" inspect --format '{{range .Mounts}}{{if eq .Destination "'"$run_root_container"'"}}{{.Source}}:{{.Destination}}:{{.RW}}{{end}}{{end}}' "$container")"
  if [[ "$observed_run_mount" != "$run_root_host:$run_root_container:true" ]]; then
    echo "ERROR: exact-run bind is absent, read-only, or drifted after container create." >&2
    exit 1
  fi
  if ! "${docker_cmd[@]}" exec --user "0:$run_root_gid" --workdir "$run_root_container" \
      "$container" sh -ceu 'test -d . && test -w . && : > .kvdelta-write-probe && rm -f .kvdelta-write-probe'; then
    echo "ERROR: unchanged container UID with exact host GID cannot write the run bind." >&2
    exit 1
  fi
fi
if [[ "$optimization_bind_enabled" == "1" ]]; then
  observed_optimization_mount="$("${docker_cmd[@]}" inspect --format '{{range .Mounts}}{{if eq .Destination "'"$optimization_src_container"'"}}{{.Source}}:{{.Destination}}:{{.RW}}{{end}}{{end}}' "$container")"
  if [[ "$observed_optimization_mount" != "$optimization_src_host:$optimization_src_container:true" ]]; then
    echo "ERROR: optimization source bind is absent, read-only, or drifted after container create." >&2
    exit 1
  fi
  if [[ -z "$engine_python" || "$engine_python" != /* ]]; then
    echo "ERROR: optimization import proof requires an absolute container Python." >&2
    exit 1
  fi
  optimization_container_module_file="$optimization_src_container/${optimization_import_module//.//}.py"
  if ! "${docker_cmd[@]}" exec --user "0:$run_root_gid" \
      --env "PYTHONPATH=$pythonpath" \
      "$container" "$engine_python" -c \
      'import importlib.util, pathlib, sys
module, expected = sys.argv[1:]
spec = importlib.util.find_spec(module)
if spec is None or spec.origin is None:
    raise SystemExit("optimization import proof: module unavailable")
if pathlib.Path(spec.origin).resolve() != pathlib.Path(expected).resolve():
    raise SystemExit("optimization import proof: module origin drift")' \
      "$optimization_import_module" "$optimization_container_module_file"; then
    echo "ERROR: optimization module is not importable from the exact mounted source." >&2
    exit 1
  fi
fi

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
if [[ -n "$compilation_config" ]]; then
  echo "[vllm-hust] compilation_config = set"
fi
echo "[vllm-hust] plugins          = $plugins"

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

IMPORT_PREFLIGHT=__IMPORT_PREFLIGHT_SHELL__
CONTAINER_LOG_FILE="__CONTAINER_LOG_FILE__"
if [[ -n "$CONTAINER_LOG_FILE" ]]; then
  mkdir -p "$(dirname "$CONTAINER_LOG_FILE")"
  exec > >(sed -u -E 's/sk-[A-Za-z0-9._-]+/<redacted>/g; s/(api-key[ =])[^ ]+/\1<redacted>/Ig; s/(Bearer )[A-Za-z0-9._~+\/-]+/\1<redacted>/g; s/([A-Za-z_]*(KEY|TOKEN|SECRET)[A-Za-z_]*=)[^ ]+/\1<redacted>/g' | tee -a "$CONTAINER_LOG_FILE") 2>&1
fi

CONDA_ENV="__CONDA_ENV__"
CONDA_PREFIX_OVERRIDE="__CONDA_PREFIX__"
ENGINE_PYTHON="__ENGINE_PYTHON__"
ENGINE_PYTHON_OVERRIDE="$ENGINE_PYTHON"
if [[ -n "$ENGINE_PYTHON" ]]; then
  echo "[container] exact engine Python selected; skipping conda activation"
elif [[ -n "$CONDA_PREFIX_OVERRIDE" ]]; then
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
if [[ -d /usr/local/lib ]]; then
  export LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH:-}"
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
export VLLM_API_KEY="__API_KEY__"
export COMPILE_CUSTOM_KERNELS="${COMPILE_CUSTOM_KERNELS:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export PYTHONPATH="__PYTHONPATH__:${PYTHONPATH:-}"

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

export HOME="__CONTAINER_HOME__"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export VLLM_CACHE_ROOT="$HOME/.cache/vllm"
export VLLM_CONFIG_ROOT="$HOME/.config/vllm"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$VLLM_CACHE_ROOT" "$VLLM_CONFIG_ROOT"
cd "__CONTAINER_WORK_ROOT__"

VLLM_BIN="__VLLM_BIN__"
VLLM_SCRIPT="__VLLM_SCRIPT__"
if [[ -n "$ENGINE_PYTHON" ]]; then
  VLLM_SCRIPT=""
fi
if [[ -n "$VLLM_SCRIPT" ]]; then
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
elif [[ -n "$ENGINE_PYTHON_OVERRIDE" ]]; then
  VLLM_BIN="$(dirname "$ENGINE_PYTHON")/vllm"
  if [[ ! -f "$VLLM_BIN" ]]; then
    echo "ERROR: expected vLLM script next to VLLM_ENGINE_PYTHON, but not found: $VLLM_BIN" >&2
    exit 1
  fi
  echo "[container] using vLLM binary: $VLLM_BIN"
fi
echo "[container] python: $ENGINE_PYTHON"
echo "[container] vllm: $("$ENGINE_PYTHON" -c 'import vllm; print(vllm.__file__)' 2>/dev/null || echo 'N/A')"
echo "[container] vllm_ascend: $("$ENGINE_PYTHON" -c 'import vllm_ascend; print(vllm_ascend.__file__)' 2>/dev/null || echo 'N/A')"
if [[ -n "__PIP_INSTALL__" ]]; then
  echo "[container] installing extra Python packages: __PIP_INSTALL__"
  # shellcheck disable=SC2086
  "$ENGINE_PYTHON" -m pip install --no-cache-dir __PIP_INSTALL__
fi
if [[ -n "$IMPORT_PREFLIGHT" ]]; then
  echo "[container] import preflight configured"
  "$ENGINE_PYTHON" -c "$IMPORT_PREFLIGHT"
fi

args=(
  "$ENGINE_PYTHON"
)
if [[ -n "$VLLM_SCRIPT" ]]; then
  args+=("$VLLM_BIN" "$VLLM_SCRIPT")
else
  args+=("$VLLM_BIN")
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

printf -v import_preflight_shell '%q' "$import_preflight"
replace "__CONDA_ENV__" "$conda_env"
replace "__CONDA_PREFIX__" "$conda_prefix"
replace "__ENGINE_PYTHON__" "$engine_python"
replace "__EXTRA_ENV_EXPORTS__" "$extra_env_exports"
replace "__IMPORT_PREFLIGHT_SHELL__" "$import_preflight_shell"
replace "__CONTAINER_LOG_FILE__" "$container_log_file"
replace "__TARGET_DEVICE__" "$target_device"
replace "__NPU_DEVICES__" "$npu_devices"
replace "__PLUGINS__" "$plugins"
replace "__FLASHCOMM1__" "$flashcomm1"
replace "__FUSED_MC2__" "$fused_mc2"
replace "__PYTHONPATH__" "$pythonpath"
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
replace "__PIP_INSTALL__" "$pip_install"
if [[ "$run_bind_enabled" == "1" ]]; then
  replace "__CONTAINER_HOME__" "$run_root_container/home"
  replace "__CONTAINER_WORK_ROOT__" "$run_root_container"
else
  replace "__CONTAINER_HOME__" "/tmp/vllm-hust-home"
  replace "__CONTAINER_WORK_ROOT__" "/tmp"
fi

tmp_host_script="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/vllm-hust-engine.XXXXXX.sh")"
chmod 600 "$tmp_host_script"
cleanup() {
  rm -f "$tmp_host_script"
}
trap cleanup EXIT

printf '#!/usr/bin/env bash\n%s\n' "$inner_script" > "$tmp_host_script"
chmod 700 "$tmp_host_script"
if ! bash -n "$tmp_host_script"; then
  echo "ERROR: fully rendered generated engine script failed bash -n." >&2
  exit 1
fi

container_script="/tmp/$(basename "$tmp_host_script")"
container_script_dir="$(dirname "$container_script")"
# Stream a daemon archive so the generated bytes never appear in argv or
# inspect metadata.  The container copy is deliberately root-owned and 0700:
# images need not contain a passwd entry for the host's numeric uid, while
# Python/getpass and framework startup expect the container's default root
# identity to resolve normally.
tar --numeric-owner --owner=0 --group=0 --mode=0700 \
  -C "$(dirname "$tmp_host_script")" -cf - "$(basename "$tmp_host_script")" \
  | "${docker_cmd[@]}" cp - "$container:$container_script_dir"

container_default_user="$("${docker_cmd[@]}" inspect --format '{{.Config.User}}' "$container")"
case "$container_default_user" in
  ""|0|0:0|root|root:root) ;;
  *)
    echo "ERROR: generated engine script requires a default-root container user." >&2
    exit 1
    ;;
esac
container_script_stat="$("${docker_cmd[@]}" exec "$container" stat -Lc '%u:%g:%a' "$container_script")"
if [[ "$container_script_stat" != "0:0:700" ]]; then
  echo "ERROR: generated engine script must be root-owned with mode 0700 in the container." >&2
  exit 1
fi

docker_exec_args=(exec)
if [[ "$run_bind_enabled" == "1" ]]; then
  docker_exec_args+=(--user "0:$run_root_gid" --workdir "$run_root_container")
fi
set +e
"${docker_cmd[@]}" "${docker_exec_args[@]}" \
  --env "VLLM_TARGET_DEVICE=$target_device" \
  --env "ASCEND_RT_VISIBLE_DEVICES=$npu_devices" \
  --env "ASCEND_VISIBLE_DEVICES=$npu_devices" \
  --env "VLLM_ENGINE_COMPILATION_CONFIG=$compilation_config" \
  --env "VLLM_ENGINE_EXTRA_ARGS_JSON=${VLLM_ENGINE_EXTRA_ARGS_JSON:-}" \
  --env "VLLM_USE_SIMPLE_KV_OFFLOAD=${VLLM_USE_SIMPLE_KV_OFFLOAD:-0}" \
  "$container" bash "$container_script"
engine_rc=$?
set -e
if (( engine_rc != 0 )) && [[ -n "$lifecycle_diagnostics_file" ]]; then
  capture_container_inspect "terminal" || true
  capture_pid_identity "terminal" "$container_pid1"
  # One post-inspect nanosecond bound closes both PID1 log and Docker-event
  # custody over the same exact terminal interval.
  terminal_capture_until="$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)"
  capture_container_runtime_logs "$terminal_capture_until" || true
  capture_docker_events "$terminal_capture_until" || true
fi
exit "$engine_rc"
