#!/usr/bin/env python3
"""Default-off Sage Mate owner transport. Not a shell or a lifecycle grant.

The protocol is installed but no production backend is qualified in this release.
All actions are parsed, then fail closed. In particular monitor/cleanup/reconcile
never reinterpret a caller's ID as authorization, restart a service or fall back.
"""

import json
from pathlib import Path
import sys

# `python -I script` excludes the script directory from sys.path. Only use the
# verified producer's own package; never import from cwd/PYTHONPATH/user site.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from instance_control.schema import ControlError, decode, fields, identifier, require  # noqa: E402

PROTOCOL = "vllm-hust.instance-owner-entry/v1"
ACTIONS = {"serve", "start", "stop", "restart", "reconcile", "cleanup", "monitor"}


def request(raw):
    require(len(raw) <= 4096, "request_too_large")
    value = decode(raw)
    fields(value, "schema consumer action instance_id owner_id profile_id new_operations_enabled invocation_id")
    require(value["schema"] == PROTOCOL and value["consumer"] == "sage-mate", "unsupported_consumer")
    require(isinstance(value["action"], str) and value["action"] in ACTIONS, "unsupported_action")
    for name in ("instance_id", "owner_id", "profile_id"):
        identifier(value[name])
    require(type(value["new_operations_enabled"]) is bool, "invalid_gate_preference")
    from instance_control.schema import hash_value
    if value["invocation_id"] is not None:
        hash_value(value["invocation_id"], 32)
    return value


def main():
    try:
        request(sys.stdin.buffer.read(4097))
        # Deliberate release gate: no store creation, locking, adapter loading or
        # subprocess. Runtime transport will be wired only after the host backend
        # and OS writer exclusion have passed separate qualification.
        raise ControlError("production_backend_not_qualified")
    except (ControlError, OSError) as exc:
        code = str(exc) if isinstance(exc, ControlError) else "transport_unavailable"
        print(json.dumps({"protocol": PROTOCOL, "error": code,
                          "lifecycleAvailable": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
