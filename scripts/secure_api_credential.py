#!/usr/bin/env python3
"""Validate, stage, consume, and delete a short-lived vLLM API credential."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from pathlib import Path


TOKEN = re.compile(rb"[A-Za-z0-9_-]{32,512}")


def _read(path: Path, expected_uid: int) -> tuple[bytes, os.stat_result]:
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError("credential must be a regular file, not a link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("credential inode changed during admission")
        if current.st_uid != expected_uid:
            raise RuntimeError("credential owner does not match the expected uid")
        if stat.S_IMODE(current.st_mode) != 0o600:
            raise RuntimeError("credential mode must be exactly 0600")
        if current.st_nlink != 1:
            raise RuntimeError("credential must have exactly one hard link")
        data = os.read(fd, 513)
        if os.read(fd, 1):
            raise RuntimeError("credential exceeds the maximum length")
    finally:
        os.close(fd)
    if TOKEN.fullmatch(data) is None:
        raise RuntimeError("credential must be 32-512 URL-safe bytes with no newline")
    return data, before


def _delete_exact(path: Path, before: os.stat_result) -> None:
    current = os.lstat(path)
    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
        raise RuntimeError("credential inode changed before deletion")
    path.unlink()


def _write_existing_empty(path: Path, data: bytes, expected_uid: int) -> None:
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if not stat.S_ISREG(current.st_mode):
            raise RuntimeError("staging destination must be a regular file")
        if current.st_uid != expected_uid:
            raise RuntimeError("staging destination owner mismatch")
        if stat.S_IMODE(current.st_mode) != 0o600 or current.st_nlink != 1:
            raise RuntimeError("staging destination must be mode 0600 with one link")
        if current.st_size != 0:
            raise RuntimeError("staging destination must be empty")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RuntimeError("credential staging write made no progress")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("validate", "consume", "delete"):
        command = sub.add_parser(action)
        command.add_argument("--path", type=Path, required=True)
        command.add_argument("--expected-uid", type=int, required=True)
        if action == "delete":
            command.add_argument("--expected-sha256", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--source", type=Path, required=True)
    snapshot.add_argument("--destination", type=Path, required=True)
    snapshot.add_argument("--expected-uid", type=int, required=True)
    args = parser.parse_args()

    if args.action == "snapshot":
        data, _ = _read(args.source, args.expected_uid)
        _write_existing_empty(args.destination, data, os.getuid())
        print(hashlib.sha256(data).hexdigest())
        return 0

    data, before = _read(args.path, args.expected_uid)
    digest = hashlib.sha256(data).hexdigest()
    if args.action == "validate":
        print(digest)
    elif args.action == "delete":
        if digest != args.expected_sha256:
            raise RuntimeError("credential digest changed before deletion")
        _delete_exact(args.path, before)
        print(digest)
    else:
        _delete_exact(args.path, before)
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"secure credential error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
