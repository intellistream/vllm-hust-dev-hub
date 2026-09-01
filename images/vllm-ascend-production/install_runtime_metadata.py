#!/usr/bin/env python3
"""Validate installed wheels and write a truthful runtime receipt."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
from pathlib import Path

from packaging.requirements import Requirement


SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True)
    parser.add_argument("--core-commit", required=True)
    parser.add_argument("--plugin-commit", required=True)
    parser.add_argument("--core-source-version", required=True)
    parser.add_argument("--plugin-source-version", required=True)
    args = parser.parse_args()

    for value in (args.core_commit, args.plugin_commit):
        if not SHA_PATTERN.fullmatch(value):
            parser.error(f"invalid source commit: {value}")

    lock = json.loads(Path(args.lock).read_text(encoding="utf-8"))
    expected = {
        "torch": lock["python_stack"]["torch"]["version"],
        "torch-npu": lock["python_stack"]["torch_npu"]["version"],
        "torchvision": lock["python_stack"]["torchvision"]["version"],
        "torchaudio": lock["python_stack"]["torchaudio"]["version"],
        "triton-ascend": lock["python_stack"]["triton_ascend"]["version"],
        "vllm": lock["vllm_core"]["package_version"],
        "vllm-ascend": lock["vllm_ascend"]["package_version"],
    }
    expected.update(
        {
            name.replace("_", "-"): value["version"]
            for name, value in lock["runtime_dependencies"].items()
        }
    )
    actual = {name: importlib.metadata.version(name) for name in expected}
    if actual != expected:
        raise RuntimeError(f"installed package mismatch: actual={actual}, expected={expected}")

    protected_roots = (
        "vllm",
        "vllm-ascend",
        "triton-ascend",
        "torch-npu",
        "torchvision",
        "torchaudio",
    )
    dependency_errors: list[str] = []
    for root in protected_roots:
        for requirement_text in importlib.metadata.requires(root) or ():
            requirement = Requirement(requirement_text)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed = importlib.metadata.version(requirement.name)
            except importlib.metadata.PackageNotFoundError:
                dependency_errors.append(f"{root}: missing {requirement}")
                continue
            if requirement.specifier and installed not in requirement.specifier:
                dependency_errors.append(
                    f"{root}: {requirement.name}=={installed} does not satisfy "
                    f"{requirement.specifier}"
                )
    if dependency_errors:
        raise RuntimeError(
            "protected runtime dependency mismatch:\n" + "\n".join(dependency_errors)
        )

    receipt_root = Path("/opt/vllm-hust-runtime")
    receipt_root.mkdir(parents=True, exist_ok=True)
    (receipt_root / "production-lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (receipt_root / "runtime-stack.json").write_text(
        json.dumps(
            {
                "schema": "vllm-hust.runtime-receipt/v2",
                "install_mode": "immutable-wheels",
                "core": {
                    "commit": args.core_commit,
                    "source_version": args.core_source_version,
                    "package_version": actual["vllm"],
                },
                "plugin": {
                    "commit": args.plugin_commit,
                    "source_version": args.plugin_source_version,
                    "package_version": actual["vllm-ascend"],
                    "verified_core": lock["vllm_core"]["commit"],
                },
                "packages": actual,
                "compatibility": lock["compatibility"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
