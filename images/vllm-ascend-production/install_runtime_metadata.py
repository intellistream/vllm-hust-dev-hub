#!/usr/bin/env python3
"""Install truthful source-snapshot metadata ahead of base image metadata."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import shutil
import site
from pathlib import Path

from packaging.version import Version


SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def _distribution(root: Path, name: str, version: str) -> None:
    normalized = name.replace("-", "_")
    target = root / f"{normalized}-{version}.dist-info"
    base = importlib.metadata.distribution(name)
    source = Path(str(base._path))
    if not source.is_dir():
        raise RuntimeError(f"base distribution metadata is unavailable: {name}")
    # Preserve console scripts, plugin entry points, licenses and package
    # metadata from the verified base wheel. A minimal shadow dist-info would
    # make the source version truthful but silently hide Ascend discovery.
    shutil.copytree(source, target)
    metadata_path = target / "METADATA"
    metadata = metadata_path.read_text(encoding="utf-8")
    metadata, replacements = re.subn(
        r"^Version:.*$", f"Version: {version}", metadata, count=1, flags=re.MULTILINE
    )
    if replacements != 1:
        raise RuntimeError(f"base distribution has no version field: {name}")
    metadata_path.write_text(metadata, encoding="utf-8")
    (target / "RECORD").unlink(missing_ok=True)
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
