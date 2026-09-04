#!/usr/bin/env python3
"""Inspect one registered host lifecycle target; mutation needs controller data."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instance_control.host_broker import PROTOCOL  # noqa: E402
from instance_control.host_client import request  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    result = request(args.socket, {"schema": PROTOCOL, "action": "describe",
                                   "instance_id": args.instance})
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
