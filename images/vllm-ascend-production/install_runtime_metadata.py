#!/usr/bin/env python3
"""Install truthful source-snapshot metadata ahead of base image metadata."""

from __future__ import annotations

import argparse
import json
import re
import site
from pathlib import Path

from packaging.version import Version


SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def _distribution(root: Path, name: str, version: str) -> None:
    normalized = name.replace("-", "_")
    target = root / f"{normalized}-{version}.dist-info"
    target.mkdir(parents=True)
    (target / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    (target / "INSTALLER").write_text("vllm-hust-runtime-lock\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-version", required=True)
    parser.add_argument("--plugin-version", required=True)
    parser.add_argument("--core-commit", required=True)
    parser.add_argument("--plugin-commit", required=True)
    parser.add_argument("--compatibility-base", required=True)
    args = parser.parse_args()

    for value in (args.core_version, args.plugin_version):
        Version(value)
    for value in (args.core_commit, args.plugin_commit):
        if not SHA_PATTERN.fullmatch(value):
            parser.error(f"invalid source commit: {value}")

    root = Path("/opt/vllm-hust-runtime-metadata")
    root.mkdir(parents=True)
    _distribution(root, "vllm", args.core_version)
    _distribution(root, "vllm-ascend", args.plugin_version)
    (root / "runtime-stack.json").write_text(
        json.dumps(
            {
                "compatibility_base": args.compatibility_base,
                "core": {"commit": args.core_commit, "version": args.core_version},
                "plugin": {
                    "commit": args.plugin_commit,
                    "version": args.plugin_version,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "sitecustomize.py").write_text(
        "import sys\n"
        "import types\n"
        "module = types.ModuleType('vllm._version')\n"
        f"module.__version__ = {args.core_version!r}\n"
        f"module.__version_tuple__ = (0, 0, {args.core_version!r})\n"
        "sys.modules.setdefault('vllm._version', module)\n",
        encoding="utf-8",
    )
    site_packages = Path(site.getsitepackages()[0])
    (site_packages / "vllm_hust_runtime_metadata.pth").write_text(
        "import sys; sys.path.insert(0, '/opt/vllm-hust-runtime-metadata')\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
