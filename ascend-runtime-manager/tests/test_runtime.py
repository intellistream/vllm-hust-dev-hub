from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hust_ascend_manager import runtime


def test_expected_torch_version_tracks_arch():
    assert runtime._expected_torch_version("x86_64") == "2.10.0"
    assert runtime._expected_torch_version("aarch64") == "2.9.0"


def test_resolve_repo_dir_requires_vllm_layout(tmp_path: Path):
    with pytest.raises(ValueError):
        runtime._resolve_repo_dir(str(tmp_path))

    (tmp_path / "pyproject.toml").write_text("[project]\nname='vllm-hust'\n", encoding="utf-8")
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements/common.txt").write_text("transformers\n", encoding="utf-8")

    assert runtime._resolve_repo_dir(str(tmp_path)) == tmp_path.resolve()


def test_check_vllm_runtime_returns_failure_when_import_fails(tmp_path: Path, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='vllm-hust'\n", encoding="utf-8")
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements/common.txt").write_text("transformers\n", encoding="utf-8")

    fake_report = {
        "repo_dir": str(tmp_path),
        "python_bin": "/usr/bin/python3",
        "python_prefix": "/usr",
        "python_library_path": "/usr/lib",
        "expected_torch_version": "2.10.0",
        "packages": {
            "torch": "2.10.0",
            "transformers": None,
            "tokenizers": None,
            "huggingface_hub": None,
            "cmake": None,
        },
        "import_ok": False,
        "import_stderr": "ModuleNotFoundError: No module named transformers",
    }

    with (
        patch("hust_ascend_manager.runtime._resolve_python_bin", return_value="/usr/bin/python3"),
        patch("hust_ascend_manager.runtime._python_library_path", return_value="/usr/lib"),
        patch("hust_ascend_manager.runtime._runtime_report", return_value=fake_report),
    ):
        rc = runtime.check_vllm_runtime(str(tmp_path), None, json_output=False)

    captured = capsys.readouterr()
    assert rc == 1
    assert "import_ok=false" in captured.out


def test_repair_vllm_runtime_runs_expected_steps(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='vllm-hust'\n", encoding="utf-8")
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements/common.txt").write_text("transformers\n", encoding="utf-8")
    (tmp_path / "requirements/build.txt").write_text("cmake>=3.26.1\ntorch==2.10.0\n", encoding="utf-8")
    (tmp_path / "vllm").mkdir()
    (tmp_path / "vllm/_C.abi3.so").write_text("binary", encoding="utf-8")
    (tmp_path / "build").mkdir()

    commands: list[list[str]] = []

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        commands.append(list(cmd))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    with (
        patch("hust_ascend_manager.runtime._resolve_python_bin", return_value="/usr/bin/python3"),
        patch("hust_ascend_manager.runtime._python_library_path", return_value="/usr/lib"),
        patch("hust_ascend_manager.runtime.subprocess.run", side_effect=fake_run),
        patch("hust_ascend_manager.runtime.check_vllm_runtime", return_value=0),
    ):
        rc = runtime.repair_vllm_runtime(str(tmp_path), None)

    assert rc == 0
    assert any(cmd[:5] == ["/usr/bin/python3", "-m", "pip", "install", "--upgrade"] and "torch==2.10.0" in cmd for cmd in commands)
    assert any(cmd[:4] == ["/usr/bin/python3", "-m", "pip", "install"] and "-r" in cmd for cmd in commands)
    assert any(cmd[:7] == ["/usr/bin/python3", "-m", "pip", "install", "-e", str(tmp_path), "--no-build-isolation"] for cmd in commands)
    assert not (tmp_path / "vllm/_C.abi3.so").exists()
    assert not (tmp_path / "build").exists()