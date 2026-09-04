#!/usr/bin/env python3
"""Atomically toggle only the bundled inert-canary broker policy."""

import argparse
import json
import os
from pathlib import Path
import stat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/vllm-hust-host-broker/policy.json")
    parser.add_argument("--enabled", choices=("true", "false"), required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("root_required")
    path = Path(args.config)
    if not path.is_absolute() or path.resolve() != path:
        raise SystemExit("invalid_config")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        value = json.load(stream)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o640
            or value.get("schema") != "vllm-hust.host-broker-policy/v1"
            or [target.get("instance_id") for target in value.get("targets", [])]
            != ["inert-canary"]):
        raise SystemExit("canary_only_policy_required")
    value["enabled"] = args.enabled == "true"
    temporary = path.with_name(path.name + ".new")
    out = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    with os.fdopen(out, "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(temporary, info.st_uid, info.st_gid)
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
