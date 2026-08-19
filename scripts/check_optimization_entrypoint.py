"""Check whether an exact Python entry point is installed."""

from __future__ import annotations

import sys
from importlib.metadata import entry_points


def has_entry_point(group: str, name: str) -> bool:
    return any(entry_point.name == name for entry_point in entry_points(group=group))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_optimization_entrypoint.py GROUP NAME")
    raise SystemExit(0 if has_entry_point(sys.argv[1], sys.argv[2]) else 1)
