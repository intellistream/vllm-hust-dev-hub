#!/usr/bin/env python3
"""Clean NPU resources left behind when a self-hosted runner job completes.

The GitHub Actions runner normally kills processes carrying its tracking
environment variable. Some accelerator workers detach from Runner.Worker and
lose that marker, so they can remain alive after a failed or canceled job. This
script is intended for ACTIONS_RUNNER_HOOK_JOB_COMPLETED.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def parse_npu_devices(value: str) -> set[int]:
    devices: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not re.fullmatch(r"\d+", item):
            raise ValueError(f"invalid NPU device list: {value!r}")
        devices.add(int(item))
    if not devices:
        raise ValueError("RUNNER_NPU_DEVICES must not be empty")
    return devices


def parse_npu_processes(text: str) -> list[dict[str, Any]]:
    """Parse the process table emitted by ``npu-smi info``."""
    processes: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        if not raw_line.startswith("|"):
            continue
        cells = [cell.strip() for cell in raw_line.split("|")]
        if len(cells) < 6:
            continue
        device_cell, pid_cell, name_cell, memory_cell = cells[1:5]
        device_match = re.fullmatch(r"(\d+)\s+(\d+)", device_cell)
        if not device_match or not pid_cell.isdigit():
            continue
        memory_match = re.search(r"\d+", memory_cell)
        processes.append(
            {
                "npu": int(device_match.group(1)),
                "pid": int(pid_cell),
                "name": name_cell,
                "memory_mb": int(memory_match.group(0)) if memory_match else None,
            }
        )
    return processes


def query_npu_processes() -> list[dict[str, Any]]:
    result = run(["npu-smi", "info"], timeout=20)
    if result.returncode != 0:
        raise RuntimeError(
            f"npu-smi failed ({result.returncode}): {result.stderr.strip()}"
        )
    return parse_npu_processes(result.stdout)


def pid_starttime(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(errors="replace")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    tail = stat.rsplit(")", 1)
    if len(tail) != 2:
        return None
    fields = tail[1].split()
    return fields[19] if len(fields) > 19 else None


def ancestor_pids() -> set[int]:
    ancestors = {os.getpid()}
    current = os.getppid()
    while current > 1 and current not in ancestors:
        ancestors.add(current)
        try:
            status = Path(f"/proc/{current}/status").read_text(errors="replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            break
        match = re.search(r"^PPid:\s+(\d+)$", status, re.MULTILINE)
        if not match:
            break
        current = int(match.group(1))
    ancestors.add(1)
    return ancestors


def remove_owned_job_containers(runner_name: str, dry_run: bool) -> bool:
    if not runner_name or not shutil_which("docker"):
        return True
    listed = run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=org.vllm-hust.runner={runner_name}",
        ]
    )
    if listed.returncode != 0:
        print(
            f"[npu-cleanup] docker list failed: {listed.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    container_ids = listed.stdout.split()
    if not container_ids:
        return True
    print(
        f"[npu-cleanup] removing {len(container_ids)} owned job container(s): "
        + ",".join(container_id[:12] for container_id in container_ids)
    )
    if dry_run:
        return True
    removed = run(["docker", "rm", "-f", *container_ids], timeout=60)
    if removed.returncode != 0:
        print(
            f"[npu-cleanup] docker removal failed: {removed.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def shutil_which(command: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def terminate_processes(devices: set[int], dry_run: bool, grace_seconds: float) -> bool:
    protected = ancestor_pids()
    candidates: list[dict[str, Any]] = []
    for process in query_npu_processes():
        pid = process["pid"]
        if process["npu"] not in devices or pid in protected:
            continue
        # npu-smi can expose host-wide entries. Only signal PIDs visible in the
        # runner container's PID namespace.
        starttime = pid_starttime(pid)
        if starttime is None:
            continue
        process["starttime"] = starttime
        candidates.append(process)

    if not candidates:
        print(f"[npu-cleanup] no residual processes on NPU {sorted(devices)}")
        return True

    for process in candidates:
        print(
            "[npu-cleanup] residual process "
            f"npu={process['npu']} pid={process['pid']} name={process['name']!r} "
            f"memory_mb={process['memory_mb']}"
        )
    if dry_run:
        return True

    for process in candidates:
        try:
            os.kill(process["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if all(pid_starttime(p["pid"]) != p["starttime"] for p in candidates):
            break
        time.sleep(0.25)

    for process in candidates:
        if pid_starttime(process["pid"]) != process["starttime"]:
            continue
        print(f"[npu-cleanup] escalating pid={process['pid']} to SIGKILL")
        try:
            os.kill(process["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass

    # Accelerator workers can remain briefly visible in /proc while the driver
    # is releasing their context. NPU ownership, not process-table reaping, is
    # the post-condition that matters for the completed-job hook.
    time.sleep(0.5)
    active_npu_pids = {
        (process["npu"], process["pid"]) for process in query_npu_processes()
    }
    remaining = [
        process
        for process in candidates
        if pid_starttime(process["pid"]) == process["starttime"]
        and (process["npu"], process["pid"]) in active_npu_pids
    ]
    if remaining:
        print(
            "[npu-cleanup] failed to terminate PIDs: "
            + ",".join(str(process["pid"]) for process in remaining),
            file=sys.stderr,
        )
        return False
    return True


def self_test() -> None:
    sample = """
| NPU     Chip              | Process id    | Process name             | Process memory(MB)      |
| 3       0                 | 3597939       | VLLMEngineCor            | 37193                   |
| No running processes found in NPU 4                                                            |
"""
    assert parse_npu_devices("2,3") == {2, 3}
    assert parse_npu_processes(sample) == [
        {"npu": 3, "pid": 3597939, "name": "VLLMEngineCor", "memory_mb": 37193}
    ]
    print("[npu-cleanup] self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--grace-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    try:
        devices = parse_npu_devices(os.environ.get("RUNNER_NPU_DEVICES", ""))
        containers_ok = remove_owned_job_containers(
            os.environ.get("RUNNER_NAME", ""), args.dry_run
        )
        processes_ok = terminate_processes(devices, args.dry_run, args.grace_seconds)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"[npu-cleanup] cleanup failed: {error}", file=sys.stderr)
        return 1
    return 0 if containers_ok and processes_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
