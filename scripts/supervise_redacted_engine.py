#!/usr/bin/env python3
"""Run one engine child while redacting and durably mirroring its output."""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Sequence


REDACTIONS = (
    (re.compile(rb"sk-[A-Za-z0-9._-]+"), b"<redacted>"),
    (re.compile(rb"(api-key[ =])[^ ]+", re.IGNORECASE), rb"\1<redacted>"),
    (re.compile(rb"(Bearer )[A-Za-z0-9._~+/=-]+"), rb"\1<redacted>"),
    (
        re.compile(rb"([A-Za-z_]*(?:KEY|TOKEN|SECRET)[A-Za-z_]*=)[^ ]+"),
        rb"\1<redacted>",
    ),
)
TEMPFAIL = 75


def redact(value: bytes) -> bytes:
    for pattern, replacement in REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def _write_once(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, value)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def supervise(
    command: Sequence[str],
    *,
    log_path: Path,
    partial_tail_path: Path,
    output: BinaryIO,
) -> int:
    if not command or not log_path.is_absolute() or not partial_tail_path.is_absolute():
        raise ValueError("command and output paths must be explicit")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    def forward(signum: int, _frame: object) -> None:
        if child.poll() is None:
            child.send_signal(signum)

    old_handlers = {
        signum: signal.signal(signum, forward)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    partial = b""
    failed = False
    try:
        assert child.stdout is not None
        with log_path.open("ab", buffering=0) as log:
            while raw := child.stdout.readline():
                value = redact(raw)
                partial = value if not value.endswith(b"\n") else b""
                try:
                    log.write(value)
                    output.write(value)
                    output.flush()
                except (BrokenPipeError, OSError):
                    failed = True
                    break
        if failed and child.poll() is None:
            child.terminate()
        returncode = child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        failed = True
        returncode = TEMPFAIL
    finally:
        if child.stdout is not None:
            child.stdout.close()
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
    if partial:
        try:
            _write_once(partial_tail_path, partial)
        except (FileExistsError, OSError):
            failed = True
    return TEMPFAIL if failed else returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--partial-tail-file", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return supervise(
        command,
        log_path=args.log_file,
        partial_tail_path=args.partial_tail_file,
        output=sys.stdout.buffer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
