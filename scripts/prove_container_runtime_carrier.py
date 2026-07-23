#!/usr/bin/env python3
"""Prove the PID1 runtime carrier through an actual no-device container create."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import tempfile
from typing import Any


CONTAINER_TARGET = "/opt/vllm-hust-runtime-carrier"
SCRIPT_RELATIVE = "scripts/ascend-container-runtime.sh"
IMAGE_RE = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")
NAME_RE = re.compile(r"^kvdelta-runtime-carrier-proof-[a-z0-9-]+$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def target_is_disjoint(target: str, parent_targets: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(target)
    if not candidate.is_absolute() or str(candidate) != target:
        return False
    for parent in parent_targets:
        root = PurePosixPath(parent)
        if candidate == root or root in candidate.parents:
            return False
    return True


def require_carrier(carrier: Path, receipt_path: Path) -> tuple[str, dict[str, Any]]:
    if carrier.is_symlink() or not carrier.is_dir():
        raise RuntimeError("carrier must be an existing non-symlink directory")
    if carrier.resolve(strict=True) != carrier:
        raise RuntimeError("carrier must already be canonical")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    script = carrier / SCRIPT_RELATIVE
    info = script.stat()
    if script.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("carrier script must be a regular single-link file")
    expected_modes = {
        carrier: 0o555,
        carrier / "scripts": 0o555,
        script: 0o555,
    }
    for path, expected in expected_modes.items():
        if stat.S_IMODE(path.stat().st_mode) != expected:
            raise RuntimeError(f"carrier mode drift: {path}")
    digest = sha256_bytes(script.read_bytes())
    if (
        receipt.get("carrier_host") != str(carrier)
        or receipt.get("carrier_container") != CONTAINER_TARGET
        or receipt.get("staged_relative_path") != SCRIPT_RELATIVE
        or receipt.get("staged_sha256") != digest
        or receipt.get("source_sha256") != digest
    ):
        raise RuntimeError("carrier receipt binding drift")
    return digest, receipt


def build_create_argv(
    docker: list[str],
    *,
    name: str,
    image: str,
    workspace: Path,
    carrier: Path,
) -> list[str]:
    if not NAME_RE.fullmatch(name):
        raise RuntimeError("proof container name is not exact and task-scoped")
    if not IMAGE_RE.fullmatch(image):
        raise RuntimeError("proof image must use an exact sha256 digest")
    if not target_is_disjoint(CONTAINER_TARGET, ("/workspace",)):
        raise RuntimeError("runtime carrier target overlaps the workspace bind")
    return [
        *docker,
        "create",
        "--name",
        name,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--entrypoint",
        "/bin/sh",
        "-v",
        f"{workspace}:/workspace:ro",
        "-v",
        f"{carrier}:{CONTAINER_TARGET}:ro",
        image,
        "-c",
        "while :; do sleep 30; done",
    ]


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {shlex.join(command)}: "
            f"{result.stderr.strip()}"
        )
    return result


def resolve_docker() -> list[str]:
    direct = ["docker"]
    if run([*direct, "info"], check=False).returncode == 0:
        return direct
    sudo = ["sudo", "-n", "docker"]
    if run([*sudo, "info"], check=False).returncode == 0:
        return sudo
    raise RuntimeError("Docker is unavailable for the CPU-only carrier proof")


def inspect_projection(data: dict[str, Any]) -> dict[str, Any]:
    host = data["HostConfig"]
    return {
        "id": data["Id"],
        "name": data["Name"],
        "config_user": data["Config"].get("User", ""),
        "privileged": host.get("Privileged"),
        "network_mode": host.get("NetworkMode"),
        "cap_drop": host.get("CapDrop") or [],
        "security_opt": host.get("SecurityOpt") or [],
        "devices": host.get("Devices") or [],
        "device_requests": host.get("DeviceRequests") or [],
        "port_bindings": host.get("PortBindings") or {},
        "binds": host.get("Binds") or [],
        "mounts": [
            {
                key: mount.get(key)
                for key in ("Type", "Source", "Destination", "Mode", "RW", "Propagation")
            }
            for mount in data.get("Mounts", [])
        ],
    }


def verify_projection(
    projection: dict[str, Any], workspace: Path, carrier: Path
) -> None:
    expected_binds = {
        f"{workspace}:/workspace:ro",
        f"{carrier}:{CONTAINER_TARGET}:ro",
    }
    if (
        projection["privileged"] is not False
        or projection["network_mode"] != "none"
        or set(projection["cap_drop"]) != {"ALL"}
        or "no-new-privileges:true" not in projection["security_opt"]
        or projection["devices"]
        or projection["device_requests"]
        or projection["port_bindings"]
        or set(projection["binds"]) != expected_binds
    ):
        raise RuntimeError("CPU-only proof create security or bind spec drift")
    destinations = [mount["Destination"] for mount in projection["mounts"]]
    if len(destinations) != len(set(destinations)):
        raise RuntimeError("final create has a duplicate/shadowed mount target")
    by_destination = {mount["Destination"]: mount for mount in projection["mounts"]}
    carrier_mount = by_destination.get(CONTAINER_TARGET)
    if (
        carrier_mount is None
        or carrier_mount["Source"] != str(carrier)
        or carrier_mount["RW"] is not False
        or carrier_mount["Type"] != "bind"
    ):
        raise RuntimeError("final create does not contain the authoritative carrier bind")


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_text = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_text)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--workspace-host", required=True)
    parser.add_argument("--carrier-host", required=True)
    parser.add_argument("--carrier-receipt", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    workspace = Path(args.workspace_host)
    carrier = Path(args.carrier_host)
    receipt_path = Path(args.carrier_receipt)
    output = Path(args.output)
    if (
        workspace.is_symlink()
        or not workspace.is_dir()
        or workspace.resolve(strict=True) != workspace
    ):
        raise RuntimeError("workspace source must be an exact canonical directory")
    carrier_sha256, carrier_receipt = require_carrier(carrier, receipt_path)
    docker = resolve_docker()
    create_argv = build_create_argv(
        docker,
        name=args.container_name,
        image=args.image,
        workspace=workspace,
        carrier=carrier,
    )
    container_id = ""
    projection: dict[str, Any] = {}
    stat_output = ""
    probe_output = ""
    cleanup_verified = False
    try:
        container_id = run(create_argv).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise RuntimeError("Docker create did not return an immutable full ID")
        inspect = json.loads(run([*docker, "inspect", container_id]).stdout)[0]
        projection = inspect_projection(inspect)
        verify_projection(projection, workspace, carrier)
        run([*docker, "start", container_id])
        target_script = f"{CONTAINER_TARGET}/{SCRIPT_RELATIVE}"
        stat_output = run(
            [
                *docker,
                "exec",
                container_id,
                "stat",
                "-Lc",
                "%u:%g:%a %n",
                CONTAINER_TARGET,
                f"{CONTAINER_TARGET}/scripts",
                target_script,
            ]
        ).stdout
        expected_stat_suffixes = {
            f"555 {CONTAINER_TARGET}",
            f"555 {CONTAINER_TARGET}/scripts",
            f"555 {target_script}",
        }
        actual_stat_suffixes = {
            " ".join(line.split()[0].split(":")[-1:] + line.split()[1:])
            for line in stat_output.splitlines()
        }
        if actual_stat_suffixes != expected_stat_suffixes:
            raise RuntimeError("container-visible carrier modes drifted")
        container_digest = run(
            [*docker, "exec", container_id, "sha256sum", target_script]
        ).stdout.split()[0]
        if container_digest != carrier_sha256:
            raise RuntimeError("container-visible carrier bytes drifted")
        probe_output = run(
            [
                *docker,
                "exec",
                "--env",
                "ASCEND_CONTAINER_RUNTIME_PROBE_ONLY=1",
                container_id,
                "bash",
                target_script,
            ]
        ).stdout
        if probe_output.strip() != "ASCEND_CONTAINER_RUNTIME_PROBE_OK":
            raise RuntimeError("container-visible carrier execution probe drifted")
    finally:
        if container_id:
            run([*docker, "rm", "-f", container_id], check=False)
        absent = run(
            [
                *docker,
                "ps",
                "-a",
                "--filter",
                f"name=^/{args.container_name}$",
                "--format",
                "{{.ID}}",
            ],
            check=False,
        )
        cleanup_verified = absent.returncode == 0 and not absent.stdout.strip()
    if not cleanup_verified:
        raise RuntimeError("CPU-only proof container cleanup was not verified")

    payload = {
        "schema_version": "vllm-hust-container-runtime-proof.v1",
        "status": "PASS",
        "host_or_live_accelerator_state_queried": False,
        "network_mode": "none",
        "physical_devices": [],
        "ports": [],
        "image": args.image,
        "container_name": args.container_name,
        "container_id": container_id,
        "container_removed": True,
        "create_argv_sha256": canonical_json_sha256(create_argv),
        "inspect_projection": projection,
        "inspect_projection_sha256": canonical_json_sha256(projection),
        "carrier_receipt_sha256": sha256_bytes(receipt_path.read_bytes()),
        "carrier_script_sha256": carrier_sha256,
        "carrier_container": carrier_receipt["carrier_container"],
        "container_stat_sha256": sha256_bytes(stat_output.encode()),
        "container_probe_stdout_sha256": sha256_bytes(probe_output.encode()),
    }
    atomic_write(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
