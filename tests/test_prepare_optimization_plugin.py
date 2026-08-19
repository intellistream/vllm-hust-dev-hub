from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "prepare_optimization_plugin.py"
ENTRYPOINT_PROBE = REPO_ROOT / "scripts" / "check_optimization_entrypoint.py"
INSTALLED_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "optimization_plugins"


def run_installer(
    repo: Path,
    target: Path,
    *,
    group: str = "vllm.general_plugins",
    name: str = "isolated_test_plugin",
    auto_install: str = "true",
    pythonpath: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if pythonpath is None:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--repo",
            str(repo),
            "--group",
            group,
            "--name",
            name,
            "--auto-install",
            auto_install,
            "--target",
            str(target),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def create_package(root: Path, *, entrypoint_name: str | None) -> Path:
    repo = root / "plugin-repo"
    package = repo / "src" / "isolated_test_plugin"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("def register():\n    return None\n")
    entrypoint = "{}"
    if entrypoint_name is not None:
        entrypoint = repr(
            {"vllm.general_plugins": [f"{entrypoint_name}=isolated_test_plugin:register"]}
        )
    (repo / "setup.py").write_text(
        "from setuptools import find_packages, setup\n"
        "setup(name='isolated-test-plugin', version='1.0.0', "
        "package_dir={'': 'src'}, packages=find_packages('src'), "
        f"entry_points={entrypoint})\n"
    )
    (repo / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
"""
    )
    return repo


def test_preinstalled_entrypoint_does_not_create_target(tmp_path: Path) -> None:
    target = tmp_path / "must-not-exist"
    result = run_installer(
        tmp_path,
        target,
        group="vllm.general_plugins",
        name="sample_general",
        auto_install="false",
        pythonpath=INSTALLED_FIXTURE,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    assert not target.exists()


def test_installer_disables_persistent_pip_cache() -> None:
    installer = INSTALLER.read_text()

    assert '"--no-cache-dir"' in installer


def test_immutable_mode_refuses_before_creating_target(tmp_path: Path) -> None:
    target = tmp_path / "must-not-exist"
    result = run_installer(tmp_path, target, auto_install="false")

    assert result.returncode != 0
    assert "AUTO_INSTALL=false forbids modifying" in result.stderr
    assert not target.exists()


def test_missing_entrypoint_installs_with_actual_python_into_target(
    tmp_path: Path,
) -> None:
    repo = create_package(tmp_path, entrypoint_name="isolated_test_plugin")
    target = tmp_path / "install-target"
    result = run_installer(repo, target)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(target)
    assert target.is_dir()
    probe_env = os.environ.copy()
    probe_env["PYTHONPATH"] = str(target)
    probe = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT_PROBE),
            "vllm.general_plugins",
            "isolated_test_plugin",
        ],
        env=probe_env,
        check=False,
    )
    assert probe.returncode == 0
    assert str(sys.executable) in result.stderr


def test_install_without_declared_entrypoint_rolls_back(tmp_path: Path) -> None:
    repo = create_package(tmp_path, entrypoint_name=None)
    target = tmp_path / "install-target"
    result = run_installer(repo, target)

    assert result.returncode != 0
    assert "installation did not register" in result.stderr
    assert not target.exists()
    assert not target.with_name(f".{target.name}.source").exists()


def test_pip_failure_rolls_back_target(tmp_path: Path) -> None:
    repo = tmp_path / "invalid-repo"
    repo.mkdir()
    target = tmp_path / "install-target"
    result = run_installer(repo, target)

    assert result.returncode != 0
    assert not target.exists()
    assert not target.with_name(f".{target.name}.source").exists()


def test_two_service_targets_do_not_share_mutable_install_state(
    tmp_path: Path,
) -> None:
    repo = create_package(tmp_path, entrypoint_name="isolated_test_plugin")
    first = tmp_path / "container-a" / "launch-a"
    second = tmp_path / "container-b" / "launch-b"

    first_result = run_installer(repo, first)
    second_result = run_installer(repo, second)
    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert first != second

    marker = first / "mutable-marker"
    marker.write_text("container-a-only")
    assert marker.exists()
    assert not (second / marker.name).exists()


def test_failed_service_cleans_process_port_script_and_install_target(
    tmp_path: Path,
) -> None:
    repo = create_package(tmp_path, entrypoint_name="isolated_test_plugin")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
  info) exit 0 ;;
  inspect)
    if [[ "${2:-}" == "-f" ]]; then echo true; fi
    exit 0
    ;;
  cp)
    cp "$2" "${3#*:}"
    exit 0
    ;;
  exec)
    shift
    while [[ "${1:-}" == "--env" ]]; do
      export "$2"
      shift 2
    done
    shift
    exec "$@"
    ;;
esac
exit 2
"""
    )
    fake_docker.chmod(0o755)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    child_pid_file = tmp_path / "child.pid"
    fake_engine = tmp_path / "failing-engine.sh"
    fake_engine.write_text(
        """#!/usr/bin/env bash
python3 -m http.server "$FAKE_ENGINE_PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
echo "$!" > "$FAKE_ENGINE_CHILD_PID_FILE"
if [[ "${FAKE_ENGINE_HOLD:-0}" == "1" ]]; then
  while true; do sleep 1; done
fi
sleep 0.5
exit 42
"""
    )
    fake_engine.chmod(0o755)

    engine_sources = tmp_path / "engine-sources"
    for module_name in ("vllm", "vllm_ascend"):
        module_dir = engine_sources / module_name
        module_dir.mkdir(parents=True)
        (module_dir / "__init__.py").write_text("")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(docker_log),
            "FAKE_ENGINE_PORT": str(port),
            "FAKE_ENGINE_CHILD_PID_FILE": str(child_pid_file),
            "FAKE_ENGINE_HOLD": "0",
            "VLLM_ENGINE_LOAD_REPO_ENV": "false",
            "VLLM_HUST_API_KEY": "test-only-key",
            "VLLM_ENGINE_MODEL_PATH": "/models/test",
            "VLLM_ENGINE_CONTAINER_NAME": "isolated-test-container",
            "VLLM_ENGINE_NPU_DEVICES": "0",
            "VLLM_ENGINE_REPLACE_EXISTING": "false",
            "VLLM_ENGINE_PYTHON": sys.executable,
            "VLLM_ENGINE_BIN": "/bin/bash",
            "VLLM_ENGINE_BASE_PYTHONPATH": str(engine_sources),
            "VLLM_ENGINE_SCRIPT": str(fake_engine),
            "VLLM_ENGINE_PORT": str(port),
            "VLLM_ENGINE_TP_SIZE": "1",
            "VLLM_OPTIMIZATION_REPO_CONTAINER": str(repo),
            "VLLM_OPTIMIZATION_ENTRYPOINT_GROUP": "vllm.general_plugins",
            "VLLM_OPTIMIZATION_PLUGIN": "isolated_test_plugin",
            "VLLM_OPTIMIZATION_AUTO_INSTALL": "true",
            "XDG_RUNTIME_DIR": str(tmp_path),
        }
    )
    command = [str(REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh")]
    first_launcher = subprocess.Popen(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        first_stdout, first_stderr = first_launcher.communicate(timeout=180)
    except subprocess.TimeoutExpired as exc:
        first_launcher.terminate()
        first_stdout, first_stderr = first_launcher.communicate(timeout=30)
        raise AssertionError(
            "launcher exceeded 180 seconds; graceful cleanup was requested\n"
            f"stdout:\n{first_stdout}\nstderr:\n{first_stderr}"
        ) from exc
    result = subprocess.CompletedProcess(
        command,
        first_launcher.returncode,
        first_stdout,
        first_stderr,
    )

    assert result.returncode == 42, result.stderr
    child_pid = int(child_pid_file.read_text())
    for _ in range(20):
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child_pid)],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
        if not state or state.startswith("Z"):
            break
        time.sleep(0.1)
    assert not state or state.startswith("Z"), f"child still running: {state}"

    with socket.socket() as port_check:
        port_check.bind(("127.0.0.1", port))

    cleanup_line = next(
        line for line in docker_log.read_text().splitlines() if ".optimization" in line
    )
    cleaned_paths = [Path(item) for item in cleanup_line.split() if item.startswith("/tmp/")]
    assert cleaned_paths
    assert all(not path.exists() for path in cleaned_paths)

    child_pid_file.unlink()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        interrupted_port = probe.getsockname()[1]
    interrupted_env = env.copy()
    interrupted_env.update(
        {
            "FAKE_ENGINE_PORT": str(interrupted_port),
            "VLLM_ENGINE_PORT": str(interrupted_port),
            "FAKE_ENGINE_HOLD": "1",
        }
    )
    launcher = subprocess.Popen(
        [str(REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh")],
        env=interrupted_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(1800):
        if child_pid_file.exists():
            break
        assert launcher.poll() is None, launcher.stderr.read() if launcher.stderr else ""
        time.sleep(0.1)
    assert child_pid_file.exists(), "fake engine did not start"
    interrupted_child_pid = int(child_pid_file.read_text())

    launcher.terminate()
    launcher.communicate(timeout=30)
    for _ in range(30):
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(interrupted_child_pid)],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
        if not state or state.startswith("Z"):
            break
        time.sleep(0.1)
    assert not state or state.startswith("Z"), f"interrupted child still running: {state}"
    with socket.socket() as port_check:
        port_check.bind(("127.0.0.1", interrupted_port))

    cleanup_lines = [
        line for line in docker_log.read_text().splitlines() if ".optimization" in line
    ]
    interrupted_paths = [
        Path(item)
        for item in cleanup_lines[-1].split()
        if item.startswith("/tmp/")
    ]
    assert interrupted_paths
    assert all(not path.exists() for path in interrupted_paths)
