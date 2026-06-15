#!/usr/bin/env python3
"""vllm_envs_smoke.py — Smoke test to verify vLLM environment imports work correctly."""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


def ensure_urllib3_parse_url() -> None:
    try:
        from urllib3.util import parse_url as _parse_url  # noqa: F401
        return
    except ModuleNotFoundError:
        urllib3_module = ModuleType("urllib3")
        urllib3_util_module = ModuleType("urllib3.util")

        def parse_url(value: str):
            scheme = value.split("://", 1)[0] if "://" in value else ""
            return type("ParsedUrl", (), {"scheme": scheme})()

        urllib3_util_module.parse_url = parse_url
        urllib3_module.util = urllib3_util_module
        sys.modules.setdefault("urllib3", urllib3_module)
        sys.modules["urllib3.util"] = urllib3_util_module


def load_get_vllm_port(repo_dir: Path):
    ensure_urllib3_parse_url()

    module_path = repo_dir / "vllm" / "envs.py"
    spec = importlib.util.spec_from_file_location("vllm_envs_smoke", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load vllm envs module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_vllm_port


def main() -> int:
    repo_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    get_vllm_port = load_get_vllm_port(repo_dir)

    with patch.dict(os.environ, {}, clear=True):
        assert get_vllm_port() is None

    with patch.dict(os.environ, {"VLLM_PORT": "5678"}, clear=True):
        assert get_vllm_port() == 5678

    for raw_value, message in (
        ("abc", "must be a valid integer"),
        ("tcp://localhost:5678", "appears to be a URI"),
    ):
        with patch.dict(os.environ, {"VLLM_PORT": raw_value}, clear=True):
            try:
                get_vllm_port()
            except ValueError as exc:
                assert message in str(exc), str(exc)
            else:
                raise AssertionError(f"Expected ValueError for {raw_value!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())