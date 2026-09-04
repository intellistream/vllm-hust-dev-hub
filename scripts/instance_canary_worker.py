#!/usr/bin/env python3
"""Inert CPU-only health leaf for host lifecycle acceptance."""

import argparse
import json
import os
from pathlib import Path
import signal
import socket


def start_ticks():
    return int(Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    path = Path(args.socket)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    running = True

    def stop(_number, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.settimeout(0.2)
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(4)
    try:
        while running:
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            with client:
                raw = client.recv(1024)
                if raw == b'{"action":"health"}\n':
                    client.sendall(json.dumps({"status": "ok", "pid": os.getpid(),
                                               "start_ticks": start_ticks()},
                                              separators=(",", ":")).encode())
    finally:
        server.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
