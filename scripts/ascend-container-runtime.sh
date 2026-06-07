#!/usr/bin/env bash
# ascend-container-runtime.sh — SSH keepalive for Ascend dev containers
# Configure via environment variables or a .env file next to this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "${SCRIPT_DIR}/../.env" ]] && set -a && source "${SCRIPT_DIR}/../.env" && set +a

# --- Required configuration (no defaults) ---
: "${CONTAINER_SSH_USER:?Error: CONTAINER_SSH_USER must be set}"

# --- Optional configuration (with sensible defaults) ---
: "${CONTAINER_SSH_PORT:=2237}"
: "${CONTAINER_SSH_AUTHORIZED_KEYS:=/workspace/.ssh/authorized_keys}"
: "${CONTAINER_SSH_PIDFILE:=/var/run/sshd_${CONTAINER_SSH_PORT}.pid}"
: "${CONTAINER_SSH_LOGFILE:=/var/log/sshd_${CONTAINER_SSH_PORT}.log}"
: "${CONTAINER_SSH_HEALTH_INTERVAL:=5}"

start_workspace_ssh() {
  if ! [[ -x /usr/sbin/sshd ]]; then
    return 0
  fi

  mkdir -p /run/sshd /var/run

  if [[ -f /etc/ssh/sshd_config.d/vllm-ascend.conf ]] && ! pgrep -f '/usr/sbin/sshd -f /etc/ssh/sshd_config' >/dev/null 2>&1; then
    /usr/sbin/sshd -f /etc/ssh/sshd_config || true
  fi

  if id -u "${CONTAINER_SSH_USER}" >/dev/null 2>&1 && [[ -f "${CONTAINER_SSH_AUTHORIZED_KEYS}" ]] && ! pgrep -f "sshd -p ${CONTAINER_SSH_PORT}" >/dev/null 2>&1; then
    /usr/sbin/sshd \
      -p "${CONTAINER_SSH_PORT}" \
      -o UsePAM=no \
      -o StrictModes=no \
      -o PermitRootLogin=no \
      -o PasswordAuthentication=no \
      -o PubkeyAuthentication=yes \
      -o "AllowUsers=${CONTAINER_SSH_USER}" \
      -o "AuthorizedKeysFile=${CONTAINER_SSH_AUTHORIZED_KEYS}" \
      -o "PidFile=${CONTAINER_SSH_PIDFILE}" \
      -E "${CONTAINER_SSH_LOGFILE}" || true
  fi
}

start_workspace_ssh

while true; do
  start_workspace_ssh
  sleep "${CONTAINER_SSH_HEALTH_INTERVAL}"
done &

trap : TERM INT
sleep infinity & wait
