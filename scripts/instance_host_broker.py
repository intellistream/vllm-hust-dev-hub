#!/usr/bin/env python3
"""Run the fixed-policy vLLM-HUST AF_UNIX host broker."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instance_control import Store  # noqa: E402
from instance_control.host_broker import BrokerPolicy, serve  # noqa: E402
from instance_control.schema import ControlError, require  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    policy = BrokerPolicy.load(args.config)
    require(policy.enabled is True, "host_authority_disabled")
    store = Store(Path(args.state), initialize=True)
    serve(store, policy)


if __name__ == "__main__":
    try:
        main()
    except (ControlError, OSError) as exc:
        code = str(exc) if isinstance(exc, ControlError) else "broker_start_failed"
        print(json.dumps({"protocol": "vllm-hust.host-broker/v1", "error": code}),
              file=sys.stderr)
        raise SystemExit(2)
