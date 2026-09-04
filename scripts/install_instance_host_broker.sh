#!/bin/bash
set -euo pipefail

# Install code and a disabled canary-only policy. This script never enrolls a
# shared service and never calls Docker, npu-smi, or a serving unit.
if [[ ${EUID} -ne 0 || $# -ne 3 ]]; then
  echo "usage: sudo $0 CONTROL_UID CONTROL_GID CONTROL_GROUP" >&2
  exit 2
fi

control_uid=$1
control_gid=$2
control_group=$3
[[ ${control_uid} =~ ^[0-9]+$ && ${control_gid} =~ ^[0-9]+$ && ${control_group} =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 2
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)

getent passwd vllm-hust-broker >/dev/null || useradd --system --home-dir /var/lib/vllm-hust-host-broker --shell /usr/sbin/nologin vllm-hust-broker
usermod -a -G "${control_group}" vllm-hust-broker
install -d -o root -g vllm-hust-broker -m 0750 /usr/lib/vllm-hust-host-broker /etc/vllm-hust-host-broker
install -d -o vllm-hust-broker -g vllm-hust-broker -m 0700 /var/lib/vllm-hust-host-broker
install -o root -g vllm-hust-broker -m 0644 "${repo}"/scripts/instance_host_broker.py "${repo}"/scripts/instance_canary_worker.py /usr/lib/vllm-hust-host-broker/
install -o root -g root -m 0750 "${repo}"/scripts/set_inert_canary_gate.py /usr/lib/vllm-hust-host-broker/
install -d -o root -g vllm-hust-broker -m 0755 /usr/lib/vllm-hust-host-broker/instance_control
install -o root -g vllm-hust-broker -m 0644 "${repo}"/scripts/instance_control/*.py /usr/lib/vllm-hust-host-broker/instance_control/

python3 - "${repo}/config/instance-host-broker.example.json" /etc/vllm-hust-host-broker/policy.json "${control_uid}" "${control_gid}" <<'PY'
import json
import os
from pathlib import Path
import sys

source, destination, uid, gid = sys.argv[1:]
value = json.loads(Path(source).read_text())
value["enabled"] = False
value["socket_gid"] = int(gid)
value["controller_uids"] = [int(uid)]
value["targets"][0]["owner_uids"] = [int(uid)]
for artifact in value["targets"][0]["artifacts"]:
    path = Path(artifact["path"])
    import hashlib
    artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact["owner_uid"] = path.stat().st_uid
    artifact["mode"] = path.stat().st_mode & 0o777
temporary = destination + ".new"
descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
with os.fdopen(descriptor, "w") as stream:
    json.dump(value, stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
os.chown(temporary, 0, int(os.environ.get("BROKER_GID", os.stat("/etc/vllm-hust-host-broker").st_gid)))
os.replace(temporary, destination)
PY

python3 - "${repo}/systemd/vllm-hust-host-broker.service" /etc/systemd/system/vllm-hust-host-broker.service "${control_group}" <<'PY'
import os
from pathlib import Path
import sys

source, destination, group = sys.argv[1:]
rendered = Path(source).read_text().replace("__CONTROL_GROUP__", group)
temporary = destination + ".new"
descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
with os.fdopen(descriptor, "w") as stream:
    stream.write(rendered)
os.chown(temporary, 0, 0)
os.replace(temporary, destination)
PY
systemctl daemon-reload
echo "installed disabled and inactive; enable/start only an approved canary or qualified instance window"
