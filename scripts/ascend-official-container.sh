#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"
MANAGER_SRC="$HUB_ROOT/ascend-runtime-manager/src"

IMAGE="${IMAGE:-}"
CONTAINER_NAME="${CONTAINER_NAME:-vllm-ascend-dev}"
HOST_WORKSPACE_ROOT="${HOST_WORKSPACE_ROOT:-$WORKSPACE_ROOT}"
CONTAINER_WORKSPACE_ROOT="${CONTAINER_WORKSPACE_ROOT:-/workspace}"
CONTAINER_WORKDIR="${CONTAINER_WORKDIR:-$CONTAINER_WORKSPACE_ROOT/vllm-hust-dev-hub}"
HOST_CACHE_DIR="${HOST_CACHE_DIR:-$HOME/.cache}"
SHM_SIZE="${SHM_SIZE:-16g}"
DEFAULT_DOCKER_DATA_ROOT="${DEFAULT_DOCKER_DATA_ROOT:-/data/docker}"
MIN_DOCKER_PULL_FREE_BYTES="$((8 * 1024 * 1024 * 1024))"
DEFAULT_CONTAINER_SSH_USER="${DEFAULT_CONTAINER_SSH_USER:-shuhao}"
DEFAULT_CONTAINER_SSH_PORT="${DEFAULT_CONTAINER_SSH_PORT:-2222}"
AUTO_ENABLE_CONTAINER_SSH="${VLLM_HUST_AUTO_ENABLE_CONTAINER_SSH:-1}"

log() {
  printf '[container] %s\n' "$1"
}

fail() {
  printf '[container] %s\n' "$1" >&2
  return 1
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  echo "python3 or python is required" >&2
  return 1
}

resolve_docker_cmd() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    printf 'docker\n'
    return 0
  fi

  if command -v docker >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    printf 'sudo -n docker\n'
    return 0
  fi

  return 1
}

docker_root_dir() {
  local -a docker_cmd=("$@")
  "${docker_cmd[@]}" info --format '{{.DockerRootDir}}'
}

path_free_bytes() {
  local target_path="$1"
  df -Pk "$target_path" | awk 'NR==2 {print $4 * 1024}'
}

docker_daemon_data_root() {
  local python_bin="$1"

  sudo -n "$python_bin" - 2>/dev/null <<'PY'
import json
from pathlib import Path

config_path = Path('/etc/docker/daemon.json')
if not config_path.exists():
    print("")
    raise SystemExit(0)

try:
    data = json.loads(config_path.read_text())
except Exception:
    print("")
    raise SystemExit(0)

print(data.get('data-root', ''))
PY
}

confirm_default_yes() {
  local prompt="$1"
  local reply=""

  if [[ ! -t 0 ]]; then
    return 1
  fi

  read -r -p "$prompt [Y/n] " reply
  if [[ -z "$reply" ]]; then
    return 0
  fi

  [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

maybe_relocate_docker_data_root() {
  local python_bin="$1"
  local action="$2"
  local docker_cmd_raw
  local configured_data_root=""
  local current_root=""
  local root_free_bytes=0
  local data_free_bytes=0
  local backup_path=""
  local temp_config

  case "$action" in
    install|start|shell|exec|ssh-enable|ssh-deploy|pull)
      ;;
    *)
      return 0
      ;;
  esac

  if [[ ! -d /data ]]; then
    return 0
  fi

  if ! docker_cmd_raw="$(resolve_docker_cmd)"; then
    return 0
  fi

  local -a docker_cmd
  read -r -a docker_cmd <<< "$docker_cmd_raw"

  current_root="$(docker_root_dir "${docker_cmd[@]}")"
  if [[ -z "$current_root" ]]; then
    return 0
  fi

  configured_data_root="$(docker_daemon_data_root "$python_bin" || true)"
  if [[ "$configured_data_root" == "$DEFAULT_DOCKER_DATA_ROOT" || "$current_root" == "$DEFAULT_DOCKER_DATA_ROOT" ]]; then
    return 0
  fi

  if [[ -n "$configured_data_root" && "$configured_data_root" != "$DEFAULT_DOCKER_DATA_ROOT" ]]; then
    log "Docker 已配置 data-root=$configured_data_root，跳过自动切换。"
    return 0
  fi

  root_free_bytes="$(path_free_bytes "$current_root")"
  data_free_bytes="$(path_free_bytes /data)"

  if (( root_free_bytes >= MIN_DOCKER_PULL_FREE_BYTES || data_free_bytes < MIN_DOCKER_PULL_FREE_BYTES )); then
    return 0
  fi

  log "检测到 Docker data-root=$current_root 空间不足，而 /data 空间充足。"
  if [[ "${VLLM_HUST_AUTO_RELOCATE_DOCKER:-0}" != "1" ]]; then
    if ! confirm_default_yes "是否将 Docker data-root 迁移到 $DEFAULT_DOCKER_DATA_ROOT 并继续启动容器？"; then
      return 0
    fi
  fi

  temp_config="$(mktemp)"
  backup_path="/etc/docker/daemon.json.vllm-hust.bak.$(date +%Y%m%d%H%M%S)"

  sudo -n "$python_bin" - <<'PY' "$DEFAULT_DOCKER_DATA_ROOT" > "$temp_config"
import json
import sys
from pathlib import Path

data_root = sys.argv[1]
config_path = Path('/etc/docker/daemon.json')

config = {}
if config_path.exists():
    with config_path.open() as fh:
        config = json.load(fh)

config['data-root'] = data_root
print(json.dumps(config, indent=2, ensure_ascii=False))
PY

  log "停止 Docker 以迁移镜像数据到 $DEFAULT_DOCKER_DATA_ROOT"
  sudo -n systemctl stop docker
  sudo -n mkdir -p "$DEFAULT_DOCKER_DATA_ROOT"

  if [[ "$current_root" != "$DEFAULT_DOCKER_DATA_ROOT" ]] && sudo -n test -d "$current_root"; then
    if ! sudo -n find "$DEFAULT_DOCKER_DATA_ROOT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
      log "复制现有 Docker 数据到 $DEFAULT_DOCKER_DATA_ROOT"
      sudo -n rsync -aHAXx --numeric-ids "$current_root"/ "$DEFAULT_DOCKER_DATA_ROOT"/
    else
      log "$DEFAULT_DOCKER_DATA_ROOT 已有内容，跳过数据复制。"
    fi
  fi

  if sudo -n test -f /etc/docker/daemon.json; then
    sudo -n cp /etc/docker/daemon.json "$backup_path"
    log "已备份 Docker 配置到 $backup_path"
  fi

  sudo -n cp "$temp_config" /etc/docker/daemon.json
  rm -f "$temp_config"

  log "重启 Docker"
  sudo -n systemctl start docker

  if [[ "$(docker_root_dir "${docker_cmd[@]}")" != "$DEFAULT_DOCKER_DATA_ROOT" ]]; then
    fail "Docker data-root 切换失败，请检查 /etc/docker/daemon.json 和 docker 服务状态。"
    return 1
  fi

  log "Docker data-root 已切换到 $DEFAULT_DOCKER_DATA_ROOT"
}

default_host_authorized_keys() {
  printf '%s/.ssh/authorized_keys\n' "$HOST_WORKSPACE_ROOT"
}

host_ssh_dir() {
  printf '%s/.ssh\n' "$HOST_WORKSPACE_ROOT"
}

default_host_container_authorized_keys() {
  printf '%s/vllm-ascend-authorized_keys.auto\n' "$(host_ssh_dir)"
}

default_host_container_extra_authorized_keys() {
  printf '%s/vllm-ascend-extra-authorized_keys\n' "$(host_ssh_dir)"
}

default_container_authorized_keys() {
  printf '%s/.ssh/vllm-ascend-authorized_keys.auto\n' "${CONTAINER_WORKSPACE_ROOT%/}"
}

host_has_public_keys() {
  compgen -G "$(host_ssh_dir)/*.pub" >/dev/null
}

default_host_private_key() {
  local pub_key
  local private_key

  for pub_key in "$(host_ssh_dir)"/*.pub; do
    if [[ ! -f "$pub_key" ]]; then
      continue
    fi

    private_key="${pub_key%.pub}"
    if [[ -f "$private_key" ]]; then
      printf '%s\n' "$private_key"
      return 0
    fi
  done

  return 1
}

prepare_container_authorized_keys_source() {
  local target_file
  local ssh_dir
  local tmp_file

  append_keys_file() {
    local source_file="$1"

    if [[ -f "$source_file" ]]; then
      sed -e '$a\' "$source_file"
    fi
  }

  ssh_dir="$(host_ssh_dir)"
  target_file="$(default_host_container_authorized_keys)"
  tmp_file="${target_file}.tmp"

  mkdir -p "$ssh_dir"
  {
    append_keys_file "$(default_host_authorized_keys)"
    append_keys_file "$(default_host_container_extra_authorized_keys)"

    local pub_key
    for pub_key in "$ssh_dir"/*.pub; do
      if [[ -f "$pub_key" ]]; then
        append_keys_file "$pub_key"
      fi
    done
  } | awk 'NF && !seen[$0]++' > "$tmp_file"

  if [[ ! -s "$tmp_file" ]]; then
    rm -f "$tmp_file"
    fail "未找到可用于容器 SSH 的公钥来源。"
    return 1
  fi

  chmod 600 "$tmp_file"
  mv "$tmp_file" "$target_file"
  printf '%s\n' "$target_file"
}

maybe_enable_container_ssh() {
  local action="$1"

  case "$action" in
    install|start)
      ;;
    *)
      printf '%s\n' "$action"
      return 0
      ;;
  esac

  if [[ "$AUTO_ENABLE_CONTAINER_SSH" != "1" ]]; then
    printf '%s\n' "$action"
    return 0
  fi

  if [[ ! -f "$(default_host_authorized_keys)" && ! -f "$(default_host_container_extra_authorized_keys)" && ! host_has_public_keys ]]; then
    log "未找到 $(default_host_authorized_keys)、$(default_host_container_extra_authorized_keys) 或任何 *.pub 公钥，跳过自动容器 SSH 配置。" >&2
    printf '%s\n' "$action"
    return 0
  fi

  log "检测到宿主机 SSH 公钥材料，将自动配置容器 SSH。" >&2
  printf 'ssh-deploy\n'
}

main() {
  local action="${1:-install}"
  local effective_action
  local suggested_private_key=""
  local python_bin
  local -a extra_container_args=()
  local -a manager_cmd

  python_bin="$(find_python)"

  case "$action" in
    help|-h|--help)
      PYTHONPATH="$MANAGER_SRC${PYTHONPATH:+:$PYTHONPATH}" \
        "$python_bin" -m hust_ascend_manager.cli container -h
      return 0
      ;;
  esac

  maybe_relocate_docker_data_root "$python_bin" "$action"
  effective_action="$(maybe_enable_container_ssh "$action")"

  if [[ "$effective_action" == "ssh-deploy" || "$effective_action" == "ssh-enable" ]]; then
    prepare_container_authorized_keys_source >/dev/null
    extra_container_args+=("--ssh-user" "$DEFAULT_CONTAINER_SSH_USER")
    extra_container_args+=("--ssh-port" "$DEFAULT_CONTAINER_SSH_PORT")
    extra_container_args+=("--authorized-keys-source" "$(default_container_authorized_keys)")
    log "容器 SSH 将使用 $(default_container_authorized_keys) 作为授权公钥来源。"
    if suggested_private_key="$(default_host_private_key)"; then
      log "建议登录命令: ssh -i $suggested_private_key -p $DEFAULT_CONTAINER_SSH_PORT $DEFAULT_CONTAINER_SSH_USER@127.0.0.1"
    fi
  fi

  manager_cmd=(
    "$python_bin" -m hust_ascend_manager.cli
    container
    "$effective_action"
    --container-name "$CONTAINER_NAME"
    --host-workspace-root "$HOST_WORKSPACE_ROOT"
    --container-workspace-root "$CONTAINER_WORKSPACE_ROOT"
    --container-workdir "$CONTAINER_WORKDIR"
    --host-cache-dir "$HOST_CACHE_DIR"
    --shm-size "$SHM_SIZE"
  )

  if [[ -n "$IMAGE" ]]; then
    manager_cmd+=(--image "$IMAGE")
  fi

  if [[ "${VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE:-0}" == "1" ]]; then
    manager_cmd+=(--non-interactive)
  fi

  manager_cmd+=("${extra_container_args[@]}")
  manager_cmd+=("${@:2}")

  PYTHONPATH="$MANAGER_SRC${PYTHONPATH:+:$PYTHONPATH}" "${manager_cmd[@]}"
}

main "$@"