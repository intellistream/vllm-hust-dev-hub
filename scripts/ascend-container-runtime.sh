#!/usr/bin/env bash

set -euo pipefail

start_workspace_ssh() {
  if ! [[ -x /usr/sbin/sshd ]]; then
    return 0
  fi

  mkdir -p /run/sshd /var/run

  if [[ -f /etc/ssh/sshd_config.d/vllm-ascend.conf ]] && ! pgrep -f '/usr/sbin/sshd -f /etc/ssh/sshd_config' >/dev/null 2>&1; then
    /usr/sbin/sshd -f /etc/ssh/sshd_config || true
  fi

  if id -u shuhao >/dev/null 2>&1 && [[ -f /workspace/.ssh/authorized_keys ]] && ! pgrep -f 'sshd -p 2235' >/dev/null 2>&1; then
    /usr/sbin/sshd \
      -p 2235 \
      -o UsePAM=no \
      -o StrictModes=no \
      -o PermitRootLogin=no \
      -o PasswordAuthentication=no \
      -o PubkeyAuthentication=yes \
      -o AllowUsers=shuhao \
      -o AuthorizedKeysFile=/workspace/.ssh/authorized_keys \
      -o PidFile=/var/run/sshd_2235.pid \
      -E /var/log/sshd_2235.log || true
  fi
}

start_workspace_ssh

while true; do
  start_workspace_ssh
  sleep 5
done &

trap : TERM INT
sleep infinity & wait
