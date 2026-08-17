#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "run as the evaluation service owner; sudo is used only for system files" >&2
  exit 2
fi

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
config_source=${1:-$repo/config/evaluation-machine-112.example.json}
install_root=/opt/vllm-hust-evaluation
config_root=/etc/vllm-hust-evaluation
state_root=/data/vllm-hust-evaluation
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

if pgrep -af 'Runner\.(Listener|Worker)|runsvc\.sh' >/dev/null; then
  echo "a GitHub Actions runner is still active; refusing to take ownership" >&2
  pgrep -af 'Runner\.(Listener|Worker)|runsvc\.sh' >&2 || true
  exit 3
fi

sudo -n install -d -m 0755 "$install_root" "$config_root" "$state_root" "$state_root/state" "$state_root/artifacts"
sudo -n install -d -o "$USER" -g "$(id -gn)" -m 0750 "$state_root/state" "$state_root/artifacts"

while IFS= read -r unit; do
  [[ -n "$unit" ]] || continue
  sudo -n systemctl disable --now "$unit" || true
done < <(sudo -n systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '/actions\.runner|github.*runner/{print $1}')

for runner in /data/actions-runners/*; do
  [[ -d "$runner" ]] || continue
  for credential in .credentials .credentials_rsaparams .runner; do
    if [[ -e "$runner/$credential" ]]; then
      sudo -n mv "$runner/$credential" "$runner/$credential.disabled-$timestamp"
    fi
  done
  sudo -n touch "$runner/DISABLED_FOR_112_EVALUATION_MACHINE"
done

sudo -n rm -rf "$install_root/dev-hub.new"
sudo -n mkdir -p "$install_root/dev-hub.new"
sudo -n cp -a "$repo/." "$install_root/dev-hub.new/"
sudo -n rm -rf "$install_root/dev-hub.previous"
if [[ -d "$install_root/dev-hub" ]]; then
  sudo -n mv "$install_root/dev-hub" "$install_root/dev-hub.previous"
fi
sudo -n mv "$install_root/dev-hub.new" "$install_root/dev-hub"
sudo -n install -m 0640 "$config_source" "$config_root/config.json"

if [[ ! -f "$config_root/secrets.env" ]]; then
  token=$(openssl rand -hex 32)
  secret=$(openssl rand -hex 32)
  umask 077
  printf 'EVALUATION_API_TOKEN=%s\nEVALUATION_HMAC_SECRET=%s\n' "$token" "$secret" \
    | sudo -n tee "$config_root/secrets.env" >/dev/null
fi
sudo -n chmod 0600 "$config_root/secrets.env"
sudo -n install -m 0644 "$repo/systemd/vllm-hust-evaluation-api.service" /etc/systemd/system/
sudo -n install -m 0644 "$repo/systemd/vllm-hust-evaluation-worker.service" /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now vllm-hust-evaluation-api.service vllm-hust-evaluation-worker.service
echo "112 evaluation-machine ownership installed; secrets remain in $config_root/secrets.env"
