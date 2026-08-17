from __future__ import annotations

import argparse
import json
import os
import subprocess

from scripts.evaluation_machine.client import request


def full_sha(repository: str, revision: str) -> str:
    if len(revision) == 40 and all(
        character in "0123456789abcdef" for character in revision
    ):
        return revision
    result = subprocess.run(
        ["git", "ls-remote", f"https://github.com/{repository}.git", revision],
        check=True,
        capture_output=True,
        text=True,
    )
    matches = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    if len(set(matches)) != 1:
        raise SystemExit(f"revision did not resolve uniquely: {repository}@{revision}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--core-revision", required=True)
    parser.add_argument("--plugin-repository", required=True)
    parser.add_argument("--plugin-revision", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--target-registry-version", required=True)
    parser.add_argument("--repeat-count", type=int, default=3)
    parser.add_argument("--npu-count", type=int, default=1)
    parser.add_argument("--priority", default="normal")
    parser.add_argument("--requested-by", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--api-url", default=os.environ["EVALUATION_API_URL"])
    args = parser.parse_args()
    payload = {
        "schema_version": 1,
        "repository": args.repository,
        "core_commit": full_sha(args.repository, args.core_revision),
        "plugin_repository": args.plugin_repository,
        "plugin_commit": full_sha(args.plugin_repository, args.plugin_revision),
        "target_id": args.target_id,
        "target_registry_version": args.target_registry_version,
        "repeat_count": args.repeat_count,
        "npu_count": args.npu_count,
        "priority": args.priority,
        "requested_by": args.requested_by,
        "source_url": args.source_url,
        "metadata": {},
    }
    request(
        "POST",
        f"{args.api_url.rstrip('/')}/v1/jobs",
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        args.idempotency_key,
    )


if __name__ == "__main__":
    main()
