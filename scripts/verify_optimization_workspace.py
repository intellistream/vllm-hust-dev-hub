#!/usr/bin/env python3
"""Verify the exact core/dev-hub/BidKV commits used for integration evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--core-sha", required=True)
    parser.add_argument("--dev-hub-sha", required=True)
    parser.add_argument("--bidkv-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    specifications = {
        "core": ("vllm-hust", args.core_sha),
        "dev_hub": ("vllm-hust-dev-hub", args.dev_hub_sha),
        "bidkv": ("vllm-hust-bidkv", args.bidkv_sha),
    }
    evidence: dict[str, object] = {"schema_version": 1, "repositories": {}}
    errors: list[str] = []
    repositories = evidence["repositories"]
    assert isinstance(repositories, dict)
    for role, (directory, expected) in specifications.items():
        repo = (args.workspace_root / directory).resolve()
        actual = git(repo, "rev-parse", "HEAD")
        dirty = bool(git(repo, "status", "--porcelain"))
        repositories[role] = {
            "path": str(repo),
            "branch": git(repo, "branch", "--show-current"),
            "expected_sha": expected,
            "actual_sha": actual,
            "dirty": dirty,
        }
        if actual != expected:
            errors.append(f"{role}: expected {expected}, found {actual}")
        if dirty:
            errors.append(f"{role}: worktree is dirty")

    evidence["verified"] = not errors
    evidence["errors"] = errors
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
