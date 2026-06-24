#!/usr/bin/env bash
# manage.sh — one-command vLLM-HUST service management for dev-hub.
#
# The engine is always launched from the host through scripts/run_vllm_hust_engine.sh,
# which then enters the configured Docker container.  This keeps the launch path
# aligned with the production/debugging flow and avoids ad-hoc container shells.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
unit_name="${VLLM_ENGINE_SYSTEMD_UNIT:-vllm-hust-dev-hub-engine.service}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unit_path="$unit_dir/$unit_name"
user_runtime_dir="/run/user/$(id -u)"
user_bus_path="$user_runtime_dir/bus"

if [[ -z "${XDG_RUNTIME_DIR:-}" && -d "$user_runtime_dir" ]]; then
  export XDG_RUNTIME_DIR="$user_runtime_dir"
fi
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "$user_bus_path" ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$user_bus_path"
fi

usage() {
  cat <<EOF
Usage: ./manage.sh <status|install|start|stop|restart|logs|health|foreground> [flags]

Actions:
  install      Install/update the user systemd unit only
  start        Install/update the unit and start vLLM-HUST
  stop         Stop vLLM-HUST
  restart      Install/update the unit and restart vLLM-HUST
  status       Show systemd status
  logs         Follow service logs
  health       Check http://127.0.0.1:\${VLLM_ENGINE_PORT:-8000}/health
  foreground   Run the engine launcher directly in the current terminal

Flags:
  --json       JSON output for status/health

Required .env:
  VLLM_HUST_API_KEY=<real non-EMPTY key>

Common .env knobs:
  VLLM_ENGINE_CONTAINER=vllm-ascend-dev
  VLLM_ENGINE_IMAGE=quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler
  VLLM_ENGINE_AUTO_CREATE_CONTAINER=true
  VLLM_ENGINE_MODEL_PATH=/data/shared_models/modelscope_cache/Qwen/Qwen3-32B
  VLLM_ENGINE_SERVED_MODEL_NAME=qwen3-32b
  VLLM_ENGINE_PORT=8000
  VLLM_ENGINE_TP_SIZE=4
  VLLM_ENGINE_NPU_DEVICES=0,1,2,3
  VLLM_ENGINE_CONDA_ENV=vllm-hust-dev
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

action="$1"
shift
json_output=false
for arg in "$@"; do
  case "$arg" in
    --json) json_output=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

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

install_unit() {
  mkdir -p "$unit_dir"
  cat > "$unit_path" <<EOF
[Unit]
Description=vLLM-HUST dev-hub engine
After=default.target

[Service]
Type=simple
WorkingDirectory=$repo_root
ExecStart=$repo_root/scripts/run_vllm_hust_engine.sh
Restart=on-failure
RestartSec=10
TimeoutStopSec=60
KillMode=control-group

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
}

require_unit() {
  if [[ ! -f "$unit_path" ]]; then
    install_unit
  fi
}

service_state_json() {
  local active sub result main_pid
  active="$(systemctl --user show "$unit_name" --property=ActiveState --value 2>/dev/null || true)"
  sub="$(systemctl --user show "$unit_name" --property=SubState --value 2>/dev/null || true)"
  result="$(systemctl --user show "$unit_name" --property=Result --value 2>/dev/null || true)"
  main_pid="$(systemctl --user show "$unit_name" --property=MainPID --value 2>/dev/null || true)"
  python3 - "$unit_name" "$active" "$sub" "$result" "$main_pid" <<'PY'
import json
import sys

print(json.dumps({
    "unit": sys.argv[1],
    "active_state": sys.argv[2],
    "sub_state": sys.argv[3],
    "result": sys.argv[4],
    "main_pid": int(sys.argv[5] or "0"),
}))
PY
}

health_url="http://127.0.0.1:${VLLM_ENGINE_PORT:-${PORT:-8000}}/health"

case "$action" in
  install)
    install_unit
    echo "Installed $unit_name at $unit_path"
    ;;
  start)
    install_unit
    systemctl --user start "$unit_name"
    systemctl --user --no-pager --full status "$unit_name" || true
    ;;
  stop)
    require_unit
    systemctl --user stop "$unit_name"
    systemctl --user --no-pager --full status "$unit_name" || true
    ;;
  restart)
    install_unit
    systemctl --user restart "$unit_name"
    systemctl --user --no-pager --full status "$unit_name" || true
    ;;
  status)
    require_unit
    if $json_output; then
      service_state_json
    else
      systemctl --user --no-pager --full status "$unit_name" || true
    fi
    ;;
  logs)
    require_unit
    exec journalctl --user -u "$unit_name" -f
    ;;
  health)
    if curl -fsS -m 5 "$health_url" >/dev/null; then
      if $json_output; then
        python3 - "$health_url" <<'PY'
import json
import sys
print(json.dumps({"ok": True, "url": sys.argv[1]}))
PY
      else
        echo "health ok: $health_url"
      fi
    else
      if $json_output; then
        python3 - "$health_url" <<'PY'
import json
import sys
print(json.dumps({"ok": False, "url": sys.argv[1]}))
PY
      else
        echo "health failed: $health_url" >&2
      fi
      exit 1
    fi
    ;;
  foreground)
    exec "$repo_root/scripts/run_vllm_hust_engine.sh"
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unsupported action: $action" >&2
    usage >&2
    exit 1
    ;;
esac
