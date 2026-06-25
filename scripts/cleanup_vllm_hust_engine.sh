#!/usr/bin/env bash
# Stop vLLM serve processes inside the configured engine container.

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

if [[ -z "${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-}}" || -z "${VLLM_ENGINE_PORT:-${PORT:-}}" ]]; then
  echo "ERROR: cleanup requires VLLM_ENGINE_CONTAINER and VLLM_ENGINE_PORT, either in .env or the caller environment." >&2
  exit 2
fi

container="${VLLM_ENGINE_CONTAINER:-${DOCKER_CONTAINER:-}}"
port="${VLLM_ENGINE_PORT:-${PORT:-}}"
docker_bin="${DOCKER_BIN:-docker}"
docker_cmd=("$docker_bin")
if [[ -n "${VLLM_ENGINE_DOCKER_SUDO:-sudo}" ]]; then
  docker_cmd=("${VLLM_ENGINE_DOCKER_SUDO:-sudo}" "$docker_bin")
fi

if ! "${docker_cmd[@]}" info >/dev/null 2>&1; then
  exit 0
fi
if ! "${docker_cmd[@]}" inspect -f '{{.State.Running}}' "$container" >/dev/null 2>&1; then
  exit 0
fi

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
  echo "[vllm-hust] stopped container vLLM process(es) on port $port: $cleaned_pids"
fi
