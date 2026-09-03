#!/usr/bin/env python3
"""Bounded thin-client transport; no production authority is enrolled yet."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instance_control.schema import ControlError, decode, fields, hash_value, identifier, require  # noqa: E402

PROTOCOL = "vllm-hust.instance-control/v1"
PARAMETERS = {
    "inspect": "instance_id",
    "plan": "instance_id candidate_id deployment_action",
    "approve": "plan_id",
    "apply": "plan_id approval",
    "disable": "plan_id approval",
    "rollback": "plan_id approval",
    "operation_status": "operation_id",
    "recover": "operation_id",
}


def parse_request(raw):
    require(len(raw) <= 4096, "request_too_large")
    value = decode(raw)
    require(isinstance(value, dict) and isinstance(value.get("action"), str)
            and value["action"] in PARAMETERS, "invalid_action")
    action = value["action"]
    fields(value, "schema action " + PARAMETERS[action])
    require(value["schema"] == PROTOCOL, "unsupported_protocol")
    for key in ("instance_id", "candidate_id"):
        if key in value:
            identifier(value[key])
    if "plan_id" in value:
        hash_value(value["plan_id"])
    if "operation_id" in value:
        hash_value(value["operation_id"], 32)
    if "deployment_action" in value:
        require(isinstance(value["deployment_action"], str)
                and value["deployment_action"] in {"apply", "disable", "rollback"}, "invalid_deployment_action")
    if "approval" in value:
        require(isinstance(value["approval"], str) and 32 <= len(value["approval"]) <= 128, "invalid_approval")
    return value


def main():
    try:
        value = parse_request(sys.stdin.buffer.read(4097))
        status = {"protocol": PROTOCOL, "authorityAvailable": False,
                  "productionBackendQualified": False, "reason": "host_backend_not_qualified"}
        if value["action"] == "inspect":
            print(json.dumps({**status, "instanceId": value["instance_id"]}))
            return 0
        # Never let a Web session or caller-supplied IDs instantiate an authority.
        # Later wiring must authenticate the peer independently of these fields.
        print(json.dumps({**status, "error": "host_backend_not_qualified"}), file=sys.stderr)
    except (ControlError, OSError) as exc:
        code = str(exc) if isinstance(exc, ControlError) else "transport_unavailable"
        print(json.dumps({"protocol": PROTOCOL, "error": code, "authorityAvailable": False}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
