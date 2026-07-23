#!/usr/bin/env python3
"""Stage the container PID1 script independently of checkout permission bits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


TARGET = "/workspace/vllm-hust-dev-hub"
SCRIPT_RELATIVE = Path("scripts/ascend-container-runtime.sh")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_regular_single_link(path: Path, label: str) -> os.stat_result:
    if path.is_symlink():
        raise SystemExit(f"{label} must not be a symlink: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SystemExit(f"{label} must be a regular single-link file: {path}")
    return info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-run-root", required=True)
    args = parser.parse_args()

    source = Path(args.source)
    run_root = Path(args.run_root)
    expected_run_root = Path(args.expected_run_root)
    if not source.is_absolute() or not run_root.is_absolute():
        raise SystemExit("source and run root must be absolute")
    if run_root != expected_run_root or run_root.resolve(strict=True) != run_root:
        raise SystemExit("run root drifted from the exact canonical run root")
    if run_root.is_symlink() or not run_root.is_dir():
        raise SystemExit("run root must be an existing non-symlink directory")

    require_regular_single_link(source, "container runtime source")
    source_bytes = source.read_bytes()
    if not source_bytes.startswith(b"#!/usr/bin/env bash\n"):
        raise SystemExit("container runtime source must have the frozen bash shebang")
    if b"\r\n" in source_bytes:
        raise SystemExit("container runtime source must use LF line endings")
    syntax = subprocess.run(
        ["bash", "-n", str(source)],
        check=False,
        capture_output=True,
        text=True,
    )
    if syntax.returncode:
        raise SystemExit(f"container runtime source failed bash -n: {syntax.stderr.strip()}")

    carrier = run_root / "container-runtime-carrier"
    receipt = run_root / "container-runtime-carrier-receipt.json"
    if carrier.exists() or carrier.is_symlink() or receipt.exists() or receipt.is_symlink():
        raise SystemExit("container runtime carrier or receipt already exists")

    temporary = Path(tempfile.mkdtemp(prefix=".container-runtime-carrier.", dir=run_root))
    try:
        scripts = temporary / "scripts"
        scripts.mkdir(mode=0o700)
        staged = scripts / SCRIPT_RELATIVE.name
        staged.write_bytes(source_bytes)
        os.chmod(staged, 0o555)
        os.chmod(scripts, 0o555)
        os.chmod(temporary, 0o555)
        os.replace(temporary, carrier)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    staged = carrier / SCRIPT_RELATIVE
    staged_info = require_regular_single_link(staged, "staged container runtime")
    if staged.read_bytes() != source_bytes:
        raise SystemExit("staged container runtime bytes differ from source")
    for path in (carrier, carrier / "scripts"):
        if stat.S_IMODE(path.stat().st_mode) != 0o555:
            raise SystemExit(f"staged carrier directory mode drift: {path}")
    if stat.S_IMODE(staged_info.st_mode) != 0o555:
        raise SystemExit("staged container runtime mode must be 0555")

    payload = {
        "schema_version": "vllm-hust-container-runtime-carrier.v1",
        "source": str(source),
        "source_sha256": sha256(source_bytes),
        "carrier_host": str(carrier),
        "carrier_container": TARGET,
        "staged_relative_path": str(SCRIPT_RELATIVE),
        "staged_sha256": sha256(staged.read_bytes()),
        "carrier_mode": "0555",
        "scripts_mode": "0555",
        "script_mode": "0555",
        "script_uid": staged_info.st_uid,
        "script_gid": staged_info.st_gid,
        "stager_python": str(Path(sys.executable).resolve()),
        "docker_mount_access": "read-and-execute-for-all; write-for-none",
    }
    receipt_tmp = receipt.with_name(f".{receipt.name}.{os.getpid()}.tmp")
    receipt_tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(receipt_tmp, 0o600)
    os.replace(receipt_tmp, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
