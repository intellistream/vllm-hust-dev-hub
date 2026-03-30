#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$HUB_ROOT/.." && pwd)"

CONTAINER_NAME="${CONTAINER_NAME:-vllm-ascend-v091-dev}"
HOST_WORKSPACE_ROOT="${HOST_WORKSPACE_ROOT:-$WORKSPACE_ROOT}"
CONTAINER_WORKSPACE_ROOT="${CONTAINER_WORKSPACE_ROOT:-/workspace}"
SSH_USER="${SSH_USER:-shuhao}"
SSH_PORT="${SSH_PORT:-2222}"
AUTHORIZED_KEYS_SOURCE="${AUTHORIZED_KEYS_SOURCE:-$HOST_WORKSPACE_ROOT/.ssh/authorized_keys}"
OFFLINE_DEB_DIR="${OFFLINE_DEB_DIR:-}"

log() {
  printf '[enable-existing-container-ssh] %s\n' "$1"
}

fail() {
  printf '[enable-existing-container-ssh] %s\n' "$1" >&2
  exit 1
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

copy_offline_packages() {
  local -a docker_cmd=("$@")
  local container_tmp='/tmp/vllm-hust-dev-hub-ssh-debs'

  [[ -n "$OFFLINE_DEB_DIR" ]] || return 0
  [[ -d "$OFFLINE_DEB_DIR" ]] || fail "OFFLINE_DEB_DIR 不存在: $OFFLINE_DEB_DIR"

  "${docker_cmd[@]}" exec "$CONTAINER_NAME" bash -lc "rm -rf '$container_tmp' && mkdir -p '$container_tmp'"

  local deb
  shopt -s nullglob
  for deb in "$OFFLINE_DEB_DIR"/*.deb; do
    "${docker_cmd[@]}" cp "$deb" "$CONTAINER_NAME:$container_tmp/$(basename -- "$deb")"
  done
  shopt -u nullglob
}

main() {
  local docker_cmd_raw
  docker_cmd_raw="$(resolve_docker_cmd)" || fail 'docker 不可用，且 sudo -n docker 也不可用。'

  local -a docker_cmd
  read -r -a docker_cmd <<< "$docker_cmd_raw"

  "${docker_cmd[@]}" inspect "$CONTAINER_NAME" >/dev/null 2>&1 || fail "容器不存在: $CONTAINER_NAME"

  [[ -f "$AUTHORIZED_KEYS_SOURCE" ]] || fail "authorized_keys 不存在: $AUTHORIZED_KEYS_SOURCE"

  local host_uid host_gid
  host_uid="$(stat -c %u "$HOST_WORKSPACE_ROOT")"
  host_gid="$(stat -c %g "$HOST_WORKSPACE_ROOT")"

  copy_offline_packages "${docker_cmd[@]}"
  "${docker_cmd[@]}" cp "$AUTHORIZED_KEYS_SOURCE" "$CONTAINER_NAME:/tmp/vllm-hust-dev-hub.authorized_keys"

  log "为容器 $CONTAINER_NAME 启用 SSH，用户=$SSH_USER，端口=$SSH_PORT"

  "${docker_cmd[@]}" exec \
    -e SSH_USER="$SSH_USER" \
    -e SSH_PORT="$SSH_PORT" \
    -e HOST_UID="$host_uid" \
    -e HOST_GID="$host_gid" \
    -e CONTAINER_WORKSPACE_ROOT="$CONTAINER_WORKSPACE_ROOT" \
    -e OFFLINE_DEB_DIR_IN_CONTAINER='/tmp/vllm-hust-dev-hub-ssh-debs' \
    "$CONTAINER_NAME" bash -lc '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

install_openssh_server() {
  if command -v sshd >/dev/null 2>&1; then
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if apt-get update && apt-get install -y openssh-server; then
      return 0
    fi
  fi

  if [[ -d "$OFFLINE_DEB_DIR_IN_CONTAINER" ]]; then
    dpkg -i \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/libmd0_1.0.4-1build1_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/libbsd0_0.11.5-1_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/libcbor0.8_0.8.0-2ubuntu1_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/libedit2_3.1-20210910-1build1_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/libfido2-1_1.10.0-1_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/libwrap0_7.6.q-31build2_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/ucf_3.0043_all.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/ncurses-term_6.3-2ubuntu0.1_all.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/openssh-client_8.9p1-3ubuntu0.14_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/openssh-sftp-server_8.9p1-3ubuntu0.14_arm64.deb \
      "$OFFLINE_DEB_DIR_IN_CONTAINER"/openssh-server_8.9p1-3ubuntu0.14_arm64.deb
      return 0
  fi

  echo openssh-server 安装失败：既无法在线 apt 安装，也没有可用的 OFFLINE_DEB_DIR >&2
  return 1
}

install_openssh_server

if ! getent group "$SSH_USER" >/dev/null; then
  groupadd -g "$HOST_GID" "$SSH_USER"
fi
if ! id -u "$SSH_USER" >/dev/null 2>&1; then
  useradd -m -u "$HOST_UID" -g "$HOST_GID" -s /bin/bash "$SSH_USER"
fi

install -d -m 700 -o "$HOST_UID" -g "$HOST_GID" "/home/$SSH_USER/.ssh"
install -m 600 -o "$HOST_UID" -g "$HOST_GID" /tmp/vllm-hust-dev-hub.authorized_keys "/home/$SSH_USER/.ssh/authorized_keys"
install -d -m 755 /run/sshd /etc/ssh/sshd_config.d
ssh-keygen -A
if [[ -f /etc/pam.d/sshd ]]; then
  sed -i "s/^session\s\+required\s\+pam_loginuid\.so/session optional pam_loginuid.so/" /etc/pam.d/sshd || true
fi
cat >/etc/ssh/sshd_config.d/99-vllm-hust-dev-hub.conf <<EOF
Port $SSH_PORT
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers $SSH_USER
AuthorizedKeysFile .ssh/authorized_keys
PidFile /run/sshd-vllm-hust-dev-hub.pid
EOF
pkill -f "/usr/sbin/sshd.*-p $SSH_PORT" || true
/usr/sbin/sshd -f /etc/ssh/sshd_config -p "$SSH_PORT"

cd "/home/$SSH_USER"
ln -sfn "$CONTAINER_WORKSPACE_ROOT" workspace
for name in \
  vllm-hust \
  vllm-hust-workstation \
  vllm-hust-website \
  vllm-hust-docs \
  vllm-ascend-hust \
  vllm-hust-benchmark \
  EvoScientist \
  vllm-hust-dev-hub \
  reference-repos; do
  if [[ -e "$CONTAINER_WORKSPACE_ROOT/$name" ]]; then
    ln -sfn "$CONTAINER_WORKSPACE_ROOT/$name" "/home/$SSH_USER/$name"
  fi
done

ls -la "/home/$SSH_USER" | sed -n "1,120p"
'
}

main "$@"
