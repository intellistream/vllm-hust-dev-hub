from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from .common import canonical_json, load_json
from .store import JobStore


def parse_busy_npus(output: str) -> set[int]:
    busy: set[int] = set()
    in_process_table = False
    for line in output.splitlines():
        if "Process id" in line and "Process name" in line:
            in_process_table = True
            continue
        if not in_process_table or "No running processes" in line:
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        first = fields[0].split() if fields else []
        if len(fields) >= 2 and first and first[0].isdigit() and fields[1].isdigit():
            busy.add(int(first[0]))
    return busy


def available_npus(config: dict[str, Any]) -> list[int]:
    configured = [int(value) for value in config["managed_npus"]]
    command = config.get("npu_process_command", ["npu-smi", "info"])
    check = subprocess.run(
        command, capture_output=True, text=True, timeout=30, check=False
    )
    if check.returncode != 0:
        return []
    busy = parse_busy_npus(check.stdout)
    return [value for value in configured if value not in busy]


def acquire_npus(
    lock_dir: Path, candidates: list[int], count: int
) -> tuple[list[int], ExitStack] | None:
    stack = ExitStack()
    chosen: list[int] = []
    lock_dir.mkdir(parents=True, exist_ok=True)
    for npu in candidates:
        handle = (lock_dir / f"npu-{npu}.lock").open("a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            continue
        stack.callback(handle.close)
        chosen.append(npu)
        if len(chosen) == count:
            return chosen, stack
    stack.close()
    return None


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def run_job(
    config: dict[str, Any], store: JobStore, job: dict[str, Any], npus: list[int]
) -> None:
    output_root = Path(config["artifact_dir"])
    final_dir = output_root / job["id"]
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{job['id']}.", dir=output_root
    ) as temporary:
        work = Path(temporary)
        request_path = work / "request.json"
        request_path.write_bytes(canonical_json(job["request"]) + b"\n")
        log_path = work / "runner.log"
        environment = os.environ.copy()
        environment.update(
            {
                "EVALUATION_JOB_ID": job["id"],
                "EVALUATION_REQUEST_FILE": str(request_path),
                "EVALUATION_ASSIGNED_NPUS": ",".join(map(str, npus)),
                "EVALUATION_OUTPUT_DIR": str(work / "result"),
            }
        )
        command = [str(value) for value in config["runner_command"]]
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
            while process.poll() is None:
                latest = store.get(job["id"])
                if latest["cancel_requested"]:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                time.sleep(5)
        exit_code = process.wait()
        (work / "worker.json").write_text(
            json.dumps(
                {
                    "job_id": job["id"],
                    "worker": f"{socket.gethostname()}:{os.getpid()}",
                    "assigned_npus": npus,
                    "exit_code": exit_code,
                    "runner_command": command,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        tree_sha = sha256_tree(work)
        (work / "BUNDLE_SHA256").write_text(tree_sha + "\n")
        shutil.move(work, final_dir)
    cancelled = store.get(job["id"])["cancel_requested"]
    store.finish(
        job["id"],
        status="cancelled"
        if cancelled
        else ("succeeded" if exit_code == 0 else "failed"),
        exit_code=exit_code,
        artifact_path=str(final_dir),
        artifact_sha256=tree_sha,
        error=None if exit_code == 0 else f"runner exited with {exit_code}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = load_json(args.config)
    state_dir = Path(config["state_dir"])
    store = JobStore(state_dir / "queue.sqlite3")
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    while True:
        if (state_dir / "MAINTENANCE").exists():
            if args.once:
                return
            time.sleep(5)
            continue
        next_job = store.next_queued()
        if next_job is None:
            if args.once:
                return
            time.sleep(5)
            continue
        count = int(next_job["request"]["npu_count"])
        allocation = acquire_npus(state_dir / "locks", available_npus(config), count)
        if allocation is None:
            if args.once:
                return
            time.sleep(5)
            continue
        npus, locks = allocation
        with locks:
            job = store.claim(next_job["id"], worker_id, npus)
            if job is not None:
                run_job(config, store, job, npus)
        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
