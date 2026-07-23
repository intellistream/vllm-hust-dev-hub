#!/usr/bin/env bash
# ascend-container-runtime.sh — SSH keepalive for Ascend dev containers
# Configure via environment variables or a .env file next to this script.

set -euo pipefail

if [[ "${ASCEND_CONTAINER_RUNTIME_PROBE_ONLY:-0}" == "1" ]]; then
  printf '%s\n' "ASCEND_CONTAINER_RUNTIME_PROBE_OK"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "${SCRIPT_DIR}/../.env" ]] && set -a && source "${SCRIPT_DIR}/../.env" && set +a

# --- Optional configuration (with sensible defaults) ---
: "${CONTAINER_SSH_USER:=shuhao}"
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

runtime_event() {
  local event="$1"
  local status="${2:-0}"
  printf '{"kind":"container-runtime","event":"%s","status":%s,"pid":%s,"bashpid":%s,"ppid":%s,"time":"%s"}\n' \
    "$event" "$status" "$$" "$BASHPID" "$PPID" \
    "$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)"
}
runtime_signal() {
  runtime_event "signal-$1" 0
}
runtime_exit() {
  local status="$1"
  runtime_event "exit" "$status"
}

trap 'runtime_signal TERM' TERM
trap 'runtime_signal INT' INT
trap 'runtime_exit "$?"' EXIT
runtime_event "start" 0
sleep infinity &
set +e
wait
runtime_wait_status=$?
set -e
runtime_event "wait-return" "$runtime_wait_status"
exit "$runtime_wait_status"
