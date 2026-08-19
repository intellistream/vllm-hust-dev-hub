#!/usr/bin/env python3
"""Prepare one optimization entry point without mutating the engine prefix."""

from __future__ import annotations

import argparse
from importlib.metadata import entry_points
from pathlib import Path
import shutil
import subprocess
import sys


def has_entry_point(group: str, name: str, extra_path: Path | None = None) -> bool:
    if extra_path is not None:
        sys.path.insert(0, str(extra_path))
    try:
        return any(ep.name == name for ep in entry_points(group=group))
    finally:
        if extra_path is not None:
            sys.path.remove(str(extra_path))


def enabled(value: str) -> bool:
    return value.lower() in {"1", "true"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--group", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--auto-install", required=True)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()

    if has_entry_point(args.group, args.name):
        print("")
        return 0

    if not enabled(args.auto_install):
        parser.error(
            f"optimization entry point {args.group}:{args.name} is not installed; "
            "VLLM_OPTIMIZATION_AUTO_INSTALL=false forbids modifying the engine environment"
        )

    if not args.repo.is_dir():
        parser.error(f"optimization repository is not mounted: {args.repo}")
    if args.target.exists():
        parser.error(f"refusing to reuse optimization install target: {args.target}")

    snapshot = args.target.with_name(f".{args.target.name}.source")
    if snapshot.exists():
        parser.error(f"refusing to reuse optimization source snapshot: {snapshot}")

    try:
        args.target.mkdir(parents=True)
        shutil.copytree(
            args.repo,
            snapshot,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git",
                ".pytest_cache",
                ".ruff_cache",
                "__pycache__",
                "*.egg-info",
            ),
        )
        print(
            f"installing {args.group}:{args.name} with engine Python "
            f"{sys.executable} into {args.target}",
            file=sys.stderr,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                str(snapshot),
                "--no-deps",
                "--no-build-isolation",
                "--target",
                str(args.target),
            ],
            check=True,
            stdout=sys.stderr,
        )
        if not has_entry_point(args.group, args.name, args.target):
            raise RuntimeError(
                "optimization installation did not register "
                f"{args.group}:{args.name}"
            )
    except BaseException:
        shutil.rmtree(args.target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)

    print(args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
