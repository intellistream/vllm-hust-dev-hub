from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import time
import urllib.request
from pathlib import Path


def request(method: str, url: str, body: bytes, idempotency_key: str | None) -> None:
    timestamp = str(int(time.time()))
    secret = os.environ["EVALUATION_HMAC_SECRET"].encode()
    signature = hmac.new(
        secret, timestamp.encode() + b"\n" + body, hashlib.sha256
    ).hexdigest()
    headers = {
        "Authorization": f"Bearer {os.environ['EVALUATION_API_TOKEN']}",
        "X-Evaluation-Timestamp": timestamp,
        "X-Evaluation-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    with urllib.request.urlopen(
        urllib.request.Request(url, body or None, headers, method=method)
    ) as response:
        print(response.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url", default=os.environ.get("EVALUATION_API_URL", "http://127.0.0.1:9112")
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    submit = subparsers.add_parser("submit")
    submit.add_argument("request", type=Path)
    submit.add_argument("--idempotency-key", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("job_id")
    cancel = subparsers.add_parser("cancel")
    cancel.add_argument("job_id")
    args = parser.parse_args()
    if args.action == "submit":
        request(
            "POST",
            f"{args.url}/v1/jobs",
            args.request.read_bytes(),
            args.idempotency_key,
        )
    elif args.action == "status":
        request("GET", f"{args.url}/v1/jobs/{args.job_id}", b"", None)
    else:
        request("POST", f"{args.url}/v1/jobs/{args.job_id}/cancel", b"", None)


if __name__ == "__main__":
    main()
