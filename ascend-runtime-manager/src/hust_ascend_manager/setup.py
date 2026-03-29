import json
import grp
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .doctor import collect_report


GROUP_MEMBERSHIP_REQUIRED_EXIT_CODE = 32
SUDO_INTERACTION_REQUIRED_EXIT_CODE = 33
DEFAULT_PIP_INDEX_MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
DEFAULT_PIP_RETRIES = 8
DEFAULT_PIP_TIMEOUT_SECONDS = 120
DEFAULT_PIP_RESUME_RETRIES = 8
DEFAULT_PIP_MIRROR_PROBE_TIMEOUT_SECONDS = 3


def _user_in_group(group_name: str) -> bool:
    try:
        target_gid = grp.getgrnam(group_name).gr_gid
    except KeyError:
        return False

    if os.getgid() == target_gid:
        return True

    return target_gid in os.getgroups()


def _run_shell(
    cmd: str,
    use_sudo: bool = False,
    requires_group: str | None = None,
    non_interactive: bool = False,
) -> int:
    shell_cmd = cmd
    if requires_group and not _user_in_group(requires_group):
        if non_interactive or not sys.stdin.isatty():
            print(
                f"[setup] current user is not in required group '{requires_group}'. "
                "Refusing to enter an interactive 'sg' password prompt in non-interactive mode."
            )
            print(
                f"[setup] add the user to '{requires_group}' and re-login, "
                "or run hust-ascend-manager setup manually from an interactive shell after switching groups."
            )
            return GROUP_MEMBERSHIP_REQUIRED_EXIT_CODE
        shell_cmd = f"sg {shlex.quote(requires_group)} -c {shlex.quote(shell_cmd)}"

    if use_sudo:
        if non_interactive or not sys.stdin.isatty():
            shell_cmd = f"sudo -n {shell_cmd}"
        else:
            shell_cmd = f"sudo {shell_cmd}"

    cmd_env = os.environ.copy()
    target_prefix = sys.prefix
    if not (Path(target_prefix) / "conda-meta").exists():
        target_prefix = cmd_env.get("CONDA_PREFIX") or target_prefix
    if (Path(target_prefix) / "conda-meta").exists():
        cmd_env["CONDA_PREFIX"] = target_prefix
        cmd_env["CONDA_DEFAULT_ENV"] = Path(target_prefix).name
        target_bin = str(Path(target_prefix) / "bin")
        path_parts = cmd_env.get("PATH", "").split(":") if cmd_env.get("PATH") else []
        if target_bin not in path_parts:
            cmd_env["PATH"] = f"{target_bin}:{cmd_env.get('PATH', '')}".rstrip(":")

    # Use non-login shell to avoid ~/.bashrc auto-activate changing conda target env.
    proc = subprocess.run(["bash", "-c", shell_cmd], env=cmd_env)
    if proc.returncode != 0 and use_sudo and (non_interactive or not sys.stdin.isatty()):
        print("[setup] sudo authentication is required for a system step, but non-interactive mode is enabled.")
        return SUDO_INTERACTION_REQUIRED_EXIT_CODE
    return proc.returncode


def _read_positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed_value = int(raw_value)
    except ValueError:
        return default

    if parsed_value <= 0:
        return default
    return parsed_value


def _url_is_reachable(url: str, timeout_seconds: int) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds):
            return True
    except (urllib.error.URLError, ValueError):
        return False


def _select_pip_index_url() -> str | None:
    explicit_index_url = os.getenv("PIP_INDEX_URL") or os.getenv("HUST_ASCEND_MANAGER_PIP_INDEX_URL")
    if explicit_index_url:
        return explicit_index_url

    if os.getenv("HUST_ASCEND_MANAGER_DISABLE_PYPI_MIRROR_AUTOSET") == "1":
        return None

    mirror_url = os.getenv("HUST_ASCEND_MANAGER_PIP_MIRROR_URL", DEFAULT_PIP_INDEX_MIRROR_URL)
    probe_timeout = _read_positive_int_env(
        "HUST_ASCEND_MANAGER_PIP_MIRROR_TIMEOUT",
        DEFAULT_PIP_MIRROR_PROBE_TIMEOUT_SECONDS,
    )
    if _url_is_reachable(mirror_url, timeout_seconds=probe_timeout):
        return mirror_url
    return None


def _pip_supports_option(option: str) -> bool:
    proc = subprocess.run(
        ["python", "-m", "pip", "install", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return False
    return option in proc.stdout


def _build_pip_install_cmd(specs: list[str]) -> list[str]:
    cmd = [
        "python",
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--retries",
        str(_read_positive_int_env("HUST_ASCEND_MANAGER_PIP_RETRIES", DEFAULT_PIP_RETRIES)),
        "--timeout",
        str(_read_positive_int_env("HUST_ASCEND_MANAGER_PIP_TIMEOUT", DEFAULT_PIP_TIMEOUT_SECONDS)),
    ]
    if _pip_supports_option("--resume-retries"):
        cmd.extend(
            [
                "--resume-retries",
                str(
                    _read_positive_int_env(
                        "HUST_ASCEND_MANAGER_PIP_RESUME_RETRIES",
                        DEFAULT_PIP_RESUME_RETRIES,
                    )
                ),
            ]
        )
    cmd.extend(specs)
    return cmd


def _build_pip_install_env() -> dict[str, str]:
    cmd_env = os.environ.copy()
    cmd_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    index_url = _select_pip_index_url()
    if index_url and not cmd_env.get("PIP_INDEX_URL"):
        cmd_env["PIP_INDEX_URL"] = index_url
        print(f"[setup] using pip index: {index_url}")

    extra_index_url = os.getenv("HUST_ASCEND_MANAGER_PIP_EXTRA_INDEX_URL")
    if extra_index_url and not cmd_env.get("PIP_EXTRA_INDEX_URL"):
        cmd_env["PIP_EXTRA_INDEX_URL"] = extra_index_url
        print(f"[setup] using pip extra index: {extra_index_url}")

    return cmd_env


def _pip_install(specs: list[str]) -> int:
    if not specs:
        return 0
    cmd = _build_pip_install_cmd(specs)
    return subprocess.run(cmd, env=_build_pip_install_env()).returncode


def _ensure_conda_env_metadata() -> None:
    conda_prefix = os.getenv("CONDA_PREFIX")
    if not conda_prefix:
        return

    prefix_path = Path(conda_prefix)
    conda_meta = prefix_path / "conda-meta"
    if not conda_meta.exists():
        return

    history = conda_meta / "history"
    if not history.exists():
        history.touch()


def load_manifest(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def setup_environment(
    manifest_path: str | None,
    apply_system: bool,
    install_python_stack: bool,
    dry_run: bool,
    non_interactive: bool = False,
) -> int:
    _ensure_conda_env_metadata()

    report = collect_report()
    manifest = load_manifest(manifest_path)

    target = manifest.get("python_stack", {}) if isinstance(manifest, dict) else {}
    target_torch = target.get("torch", "2.9.0")
    target_torch_npu = target.get("torch_npu", "2.9.0")

    print("[setup] start")
    print(f"[setup] manifest: {manifest_path or '<none>'}")

    if install_python_stack:
        current = report["python_stack"]
        specs: list[str] = []
        if current.get("torch") != target_torch:
            specs.append(f"torch=={target_torch}")
        if current.get("torch_npu") != target_torch_npu:
            specs.append(f"torch-npu=={target_torch_npu}")

        if specs:
            print(f"[setup] python stack reconcile needed: {specs}")
            if not dry_run:
                rc = _pip_install(specs)
                if rc != 0:
                    print("[setup] python stack install failed")
                    return rc
        else:
            print("[setup] python stack already aligned")

    steps = manifest.get("system_steps", []) if isinstance(manifest, dict) else []
    if steps:
        print(f"[setup] loaded {len(steps)} system steps")
    for step in steps:
        desc = step.get("description", step.get("id", "unnamed-step"))
        cmd = step.get("run")
        use_sudo = bool(step.get("requires_sudo", False))
        requires_group = step.get("requires_group")
        if not cmd:
            continue
        if not apply_system:
            print(f"[setup][plan] {desc}: {cmd}")
            continue
        print(f"[setup][run] {desc}")
        if requires_group:
            print(f"[setup][run] requires group: {requires_group}")
        if dry_run:
            continue
        rc = _run_shell(
            cmd,
            use_sudo=use_sudo,
            requires_group=requires_group,
            non_interactive=non_interactive,
        )
        if rc != 0:
            print(f"[setup] failed step: {desc}")
            return rc

    print("[setup] done")
    return 0
