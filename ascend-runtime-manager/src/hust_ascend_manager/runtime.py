from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _resolve_repo_dir(repo_dir: str | None) -> Path:
    path = Path(repo_dir or os.getcwd()).resolve()
    if not (path / "pyproject.toml").exists() or not (path / "requirements/common.txt").exists():
        raise ValueError(f"Not a vllm-hust repo root: {path}")
    return path


def _resolve_python_bin(python_bin: str | None) -> str:
    if python_bin:
        candidate = shutil.which(python_bin) if not os.path.isabs(python_bin) else python_bin
        if candidate and os.access(candidate, os.X_OK):
            return candidate
        raise ValueError(f"Python interpreter is not executable: {python_bin}")

    for candidate in ("python3", "python"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise ValueError("Unable to resolve a Python interpreter")


def _python_prefix_from_bin(python_bin: str) -> Path:
    return Path(python_bin).resolve().parent.parent


def _python_library_path(python_bin: str) -> str | None:
    prefix = _python_prefix_from_bin(python_bin)
    lib_dir = prefix / "lib"
    if lib_dir.is_dir():
        return str(lib_dir)
    return None


def _expected_torch_version(machine: str | None = None) -> str:
    host_machine = machine or platform.machine()
    return "2.9.0" if host_machine == "aarch64" else "2.10.0"


def _runtime_env(repo_dir: Path, python_bin: str, library_path: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(repo_dir) + (f":{env['PYTHONPATH']}" if env.get("PYTHONPATH") else "")
    if library_path:
        env["LD_LIBRARY_PATH"] = library_path + (f":{env['LD_LIBRARY_PATH']}" if env.get("LD_LIBRARY_PATH") else "")
    env["VLLM_HUST_PYTHON_BIN"] = python_bin
    return env


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)


def _package_version(python_bin: str, repo_dir: Path, library_path: str | None, package_name: str) -> str | None:
    env = _runtime_env(repo_dir, python_bin, library_path)
    proc = subprocess.run(
        [
            python_bin,
            "-c",
            (
                "from importlib.metadata import PackageNotFoundError, version; "
                f"pkg={package_name!r}; "
                "\ntry:\n print(version(pkg))\nexcept PackageNotFoundError:\n print('')"
            ),
        ],
        cwd=str(repo_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    value = proc.stdout.strip()
    return value or None


def _import_check(python_bin: str, repo_dir: Path, library_path: str | None) -> subprocess.CompletedProcess[str]:
    env = _runtime_env(repo_dir, python_bin, library_path)
    return _run(
        [python_bin, "-c", "import torch, transformers, tokenizers, huggingface_hub; import vllm.entrypoints.cli.main"],
        cwd=repo_dir,
        env=env,
    )


def _runtime_report(repo_dir: Path, python_bin: str, library_path: str | None) -> dict[str, Any]:
    check = _import_check(python_bin, repo_dir, library_path)
    return {
        "repo_dir": str(repo_dir),
        "python_bin": python_bin,
        "python_prefix": str(_python_prefix_from_bin(python_bin)),
        "python_library_path": library_path,
        "expected_torch_version": _expected_torch_version(),
        "packages": {
            "torch": _package_version(python_bin, repo_dir, library_path, "torch"),
            "transformers": _package_version(python_bin, repo_dir, library_path, "transformers"),
            "tokenizers": _package_version(python_bin, repo_dir, library_path, "tokenizers"),
            "huggingface_hub": _package_version(python_bin, repo_dir, library_path, "huggingface_hub"),
            "cmake": _package_version(python_bin, repo_dir, library_path, "cmake"),
        },
        "import_ok": check.returncode == 0,
        "import_stderr": check.stderr.strip() or None,
    }


def _print_report(report: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return

    print(f"repo_dir={report['repo_dir']}")
    print(f"python_bin={report['python_bin']}")
    print(f"python_prefix={report['python_prefix']}")
    if report["python_library_path"]:
        print(f"python_library_path={report['python_library_path']}")
    print(f"expected_torch_version={report['expected_torch_version']}")
    for key, value in report["packages"].items():
        print(f"{key}={value or '<missing>'}")
    print(f"import_ok={str(report['import_ok']).lower()}")
    if report["import_stderr"]:
        print(report["import_stderr"])


def check_vllm_runtime(repo_dir: str | None, python_bin: str | None, json_output: bool = False) -> int:
    resolved_repo = _resolve_repo_dir(repo_dir)
    resolved_python = _resolve_python_bin(python_bin)
    library_path = _python_library_path(resolved_python)
    report = _runtime_report(resolved_repo, resolved_python, library_path)
    _print_report(report, json_output=json_output)
    return 0 if report["import_ok"] else 1


def _install_requirements_without_torch(python_bin: str, repo_dir: Path, library_path: str | None, requirements_path: Path) -> None:
    env = _runtime_env(repo_dir, python_bin, library_path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        for line in requirements_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("torch"):
                continue
            handle.write(line + "\n")
        temp_name = handle.name
    try:
        subprocess.run([python_bin, "-m", "pip", "install", "-r", temp_name], cwd=str(repo_dir), env=env, check=True)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _clean_local_build_artifacts(repo_dir: Path) -> None:
    shutil.rmtree(repo_dir / "build", ignore_errors=True)
    for pattern in ("_C*.so", "_moe_C*.so", "_flashmla_C*.so"):
        for artifact in (repo_dir / "vllm").glob(pattern):
            artifact.unlink(missing_ok=True)


def repair_vllm_runtime(
    repo_dir: str | None,
    python_bin: str | None,
    *,
    skip_torch_install: bool = False,
    skip_build_deps: bool = False,
    skip_rebuild: bool = False,
) -> int:
    resolved_repo = _resolve_repo_dir(repo_dir)
    resolved_python = _resolve_python_bin(python_bin)
    library_path = _python_library_path(resolved_python)
    env = _runtime_env(resolved_repo, resolved_python, library_path)

    if not skip_torch_install:
        subprocess.run(
            [resolved_python, "-m", "pip", "install", "--upgrade", f"torch=={_expected_torch_version()}"] ,
            cwd=str(resolved_repo),
            env=env,
            check=True,
        )

    subprocess.run(
        [resolved_python, "-m", "pip", "install", "--upgrade", "-r", "requirements/common.txt", "huggingface_hub>=0.36.0"],
        cwd=str(resolved_repo),
        env=env,
        check=True,
    )
    subprocess.run(
        [
            resolved_python,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            "transformers>=4.56.0,<5",
            "tokenizers>=0.21.1",
            "huggingface_hub>=0.36.0",
        ],
        cwd=str(resolved_repo),
        env=env,
        check=True,
    )

    if not skip_build_deps:
        _install_requirements_without_torch(resolved_python, resolved_repo, library_path, resolved_repo / "requirements/build.txt")

    if not skip_rebuild:
        _clean_local_build_artifacts(resolved_repo)
        subprocess.run(
            [resolved_python, "-m", "pip", "install", "-e", str(resolved_repo), "--no-build-isolation", "--no-deps", "--force-reinstall"],
            cwd=str(resolved_repo),
            env=env,
            check=True,
        )

    return check_vllm_runtime(str(resolved_repo), resolved_python, json_output=False)