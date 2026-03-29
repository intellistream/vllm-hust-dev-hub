import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any


_ASCEND_ENV_EXPORT_KEYS = (
    "ASCEND_HOME_PATH",
    "ASCEND_OPP_PATH",
    "ASCEND_AICPU_PATH",
    "TORCH_DEVICE_BACKEND_AUTOLOAD",
    "HUST_ASCEND_RUNTIME_VERSION",
    "HUST_ASCEND_HAS_STREAM_ATTR",
    "HUST_ASCEND_OPP_OVERLAY_ROOT",
    "HUST_ATB_SET_ENV",
)


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip().strip('"')
    return data


def _find_toolkit_root() -> str | None:
    env_candidates = [
        os.getenv("ASCEND_HOME_PATH"),
        os.getenv("ASCEND_TOOLKIT_HOME"),
        os.getenv("ASCEND_AICPU_PATH"),
    ]
    for candidate in env_candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if (candidate_path / "runtime/lib64").is_dir():
            return str(candidate_path)

    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        candidates = [
            Path(conda_prefix) / "Ascend/cann",
            Path(conda_prefix) / "Ascend/ascend-toolkit/latest",
        ]
        for c in candidates:
            if (c / "runtime/lib64").is_dir():
                return str(c)

    candidates = [
        *sorted(Path("/usr/local/Ascend").glob("cann-*"), reverse=True),
        Path("/usr/local/Ascend/ascend-toolkit/latest"),
        Path("/usr/local/Ascend/ascend-toolkit.bak.8.1/latest"),
    ]
    for c in candidates:
        if (c / "runtime/lib64").is_dir():
            return str(c)

    ascend_root = Path("/usr/local/Ascend")
    if not ascend_root.is_dir():
        return None
    all_latest = sorted(ascend_root.glob("**/latest"))
    for c in reversed(all_latest):
        if (c / "runtime/lib64").is_dir():
            return str(c)
    return None


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in paths:
        if not item:
            continue
        normalized = str(Path(item)) if os.path.isabs(item) else item
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _find_hccl(root: str | None) -> str | None:
    if not root:
        return None
    root_path = Path(root)
    parent = root_path.parent
    checks = [
        root_path / "lib64/libhccl.so",
        parent / "hccl/lib64/libhccl.so",
        root_path / "hccl/lib64/libhccl.so",
        root_path / "compiler/lib64/libhccl.so",
    ]
    for p in checks:
        if p.exists():
            return str(p)
    for p in parent.glob("*/hccl/lib64/libhccl.so"):
        if p.exists():
            return str(p)
    return None


def _collect_runtime_lib_dirs(root: str, hccl_lib: str | None) -> list[str]:
    root_path = Path(root)
    candidates = [
        root_path / "lib64",
        root_path / "runtime/lib64",
        root_path / "compiler/lib64",
        root_path / "aarch64-linux/lib64",
        root_path / "aarch64-linux/lib64/device/lib64",
        root_path / "aarch64-linux/devlib",
        root_path / "aarch64-linux/devlib/device",
        root_path / "opp/built-in/op_impl/ai_core/tbe/op_tiling",
        root_path / "opp/built-in/op_impl/ai_core/tbe/op_tiling/lib/linux/aarch64",
        root_path / "lib64/plugin/opskernel",
        root_path / "lib64/plugin/nnengine",
        root_path / "tools/aml/lib64",
        root_path / "tools/aml/lib64/plugin",
    ]

    parent = root_path.parent
    candidates.extend(
        [
            parent / "hccl/lib64",
            parent / "compiler/lib64",
            parent / "aarch64-linux/lib64",
            parent / "driver/lib64",
            parent / "driver/lib64/common",
            parent / "driver/lib64/driver",
        ]
    )

    if hccl_lib:
        candidates.append(Path(hccl_lib).parent)
        candidates.append(Path(hccl_lib).resolve().parent)

    existing = [str(path) for path in candidates if path.is_dir()]
    return _dedupe_paths(existing)


def _detect_broken_legacy_kernel_layout(root: str | None) -> dict[str, str] | None:
    if not root:
        return None

    kernel_root = Path(root) / "opp/built-in/op_impl/ai_core/tbe/kernel"
    config_root = kernel_root / "config/ascend910_93/ops_legacy"
    if not config_root.is_dir():
        return None

    probes = [
        config_root / "zeros_like.json",
        config_root / "add.json",
        config_root / "cast.json",
    ]
    for config_path in probes:
        if not config_path.exists():
            continue

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        for entry in data.get("binList", []):
            json_file_path = entry.get("binInfo", {}).get("jsonFilePath")
            if not json_file_path:
                continue

            direct_path = kernel_root / json_file_path
            if direct_path.exists():
                continue

            legacy_path = (
                kernel_root
                / "ascend910_93/ops_legacy"
                / Path(json_file_path).parent.name
                / Path(json_file_path).name
            )
            if legacy_path.exists():
                return {
                    "probe_config": str(config_path),
                    "missing_kernel_json": str(direct_path),
                    "legacy_kernel_json": str(legacy_path),
                    "message": (
                        "Detected a broken Ascend OPP legacy kernel layout: dynamic kernel "
                        "configs reference kernel/ascend910_93/<op>/..., but the installed "
                        "files only exist under kernel/ascend910_93/ops_legacy/<op>/.... "
                        "This breaks basic torch_npu ops such as torch.zeros(). Reinstall or "
                        "repair the host CANN ops package before using vLLM on this machine."
                    ),
                }

    return None


def _opp_overlay_cache_dir() -> Path:
    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "hust-ascend-manager" / "opp-overlays"
    return Path.home() / ".cache" / "hust-ascend-manager" / "opp-overlays"


def _symlink_force(target: Path, link_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink() or link_path.exists():
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink()
    link_path.symlink_to(target)


def _ensure_legacy_kernel_overlay(root: str) -> str:
    root_path = Path(root)
    real_opp_root = root_path / "opp"
    kernel_root = real_opp_root / "built-in/op_impl/ai_core/tbe/kernel"
    legacy_ops_root = kernel_root / "ascend910_93/ops_legacy"
    if not legacy_ops_root.is_dir():
        return str(real_opp_root)

    cache_key = sha256(str(root_path).encode("utf-8")).hexdigest()[:16]
    overlay_root = _opp_overlay_cache_dir() / cache_key
    overlay_opp_root = overlay_root / "opp"
    overlay_kernel_root = overlay_opp_root / "built-in/op_impl/ai_core/tbe/kernel"
    overlay_ascend_root = overlay_kernel_root / "ascend910_93"

    tmp_root = overlay_root.with_name(f"{overlay_root.name}.tmp-{os.getpid()}")
    if tmp_root.exists():
        shutil.rmtree(tmp_root)

    tmp_opp_root = tmp_root / "opp"
    tmp_kernel_root = tmp_opp_root / "built-in/op_impl/ai_core/tbe/kernel"
    tmp_ascend_root = tmp_kernel_root / "ascend910_93"
    tmp_ascend_root.mkdir(parents=True, exist_ok=True)

    _symlink_force(kernel_root / "config", tmp_kernel_root / "config")
    _symlink_force(legacy_ops_root, tmp_ascend_root / "ops_legacy")

    for op_dir in legacy_ops_root.iterdir():
        if not op_dir.is_dir():
            continue
        _symlink_force(op_dir, tmp_ascend_root / op_dir.name)

    (tmp_root / ".source-root").write_text(str(root_path), encoding="utf-8")

    overlay_root.parent.mkdir(parents=True, exist_ok=True)
    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    tmp_root.rename(overlay_root)

    if not overlay_kernel_root.exists() or not overlay_ascend_root.exists():
        raise RuntimeError(f"Failed to construct Ascend OPP overlay under {overlay_root}")

    return str(overlay_opp_root)


def _ascend_has_stream_attr(root: str | None) -> bool:
    if not root:
        return False
    root_path = Path(root)
    libs = list(root_path.glob("**/lib64/libascendcl.so"))
    for lib in libs:
        rc, out, _ = _run(["strings", str(lib)])
        if rc == 0 and "aclrtSetStreamAttribute" in out:
            return True
    return False


def _pip_version(pkg: str) -> str | None:
    rc, out, _ = _run(["python", "-m", "pip", "show", pkg])
    if rc != 0:
        return None
    m = re.search(r"^Version:\s*(.+)$", out, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


def _find_atb_lib_dir(root: str | None = None) -> str | None:
    candidates: list[Path] = []

    if root:
        root_path = Path(root)
        root_parent = root_path.parent
        candidates.extend(
            [
                root_path / "nnal/atb/latest/atb/cxx_abi_1/lib",
                root_path / "nnal/atb/atb/cxx_abi_1/lib",
                root_parent / "nnal/atb/latest/atb/cxx_abi_1/lib",
                root_parent / "nnal/atb/atb/cxx_abi_1/lib",
                root_parent / "nnal/atb/8.5.0/atb/cxx_abi_1/lib",
            ]
        )

    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        candidates.extend(
            [
                Path(conda_prefix) / "Ascend/cann/nnal/atb/latest/atb/cxx_abi_1/lib",
                Path(conda_prefix) / "Ascend/cann/nnal/atb/atb/cxx_abi_1/lib",
            ]
        )

    candidates = [
        *candidates,
        Path("/usr/local/Ascend/nnal/atb/latest/atb/cxx_abi_1/lib"),
    ]
    if Path("/usr/local/Ascend/nnal/atb").exists():
        candidates.extend(Path("/usr/local/Ascend/nnal/atb").glob("*/atb/cxx_abi_1/lib"))
    for c in candidates:
        if (c / "libatb.so").exists():
            return str(c)
    return None


def _find_atb_set_env(root: str | None = None) -> str | None:
    candidates: list[Path] = []

    if root:
        root_path = Path(root)
        root_parent = root_path.parent
        candidates.extend(
            [
                root_path / "nnal/atb/set_env.sh",
                root_path / "nnal/atb/latest/set_env.sh",
                root_parent / "nnal/atb/set_env.sh",
                root_parent / "nnal/atb/latest/set_env.sh",
            ]
        )

    conda_prefix = os.getenv("CONDA_PREFIX")
    if conda_prefix:
        candidates.extend(
            [
                Path(conda_prefix) / "Ascend/cann/nnal/atb/set_env.sh",
                Path(conda_prefix) / "Ascend/cann/nnal/atb/latest/set_env.sh",
            ]
        )

    candidates.extend(
        [
            Path("/usr/local/Ascend/nnal/atb/set_env.sh"),
            Path("/usr/local/Ascend/nnal/atb/latest/set_env.sh"),
        ]
    )

    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _sanitize_ld_path(old_ld: str) -> str:
    kept: list[str] = []
    for item in old_ld.split(":"):
        if not item:
            continue
        if "/Ascend/" in item:
            continue
        kept.append(item)
    return ":".join(kept)


def _has_active_vendor_ascend_env(root: str) -> bool:
    active_root_candidates = [
        os.getenv("ASCEND_HOME_PATH"),
        os.getenv("ASCEND_TOOLKIT_HOME"),
        os.getenv("ASCEND_AICPU_PATH"),
    ]
    current_ld = os.getenv("LD_LIBRARY_PATH", "")
    root_path = Path(root)
    return any(candidate and Path(candidate) == root_path for candidate in active_root_candidates) and "/Ascend/" in current_ld


def _probe_torch_npu_import(env: dict[str, str]) -> tuple[bool, str | None]:
    probe_env = os.environ.copy()
    probe_env.update(env)
    proc = subprocess.run(
        [sys.executable, "-c", "import torch_npu"],
        capture_output=True,
        text=True,
        env=probe_env,
    )
    if proc.returncode == 0:
        return True, None
    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()
    return False, stderr or stdout or f"exit code {proc.returncode}"


def build_env_dict(ascend_root: str | None = None) -> dict[str, str]:
    root = ascend_root or _find_toolkit_root()
    if not root:
        raise RuntimeError("Could not discover Ascend runtime root")

    root_path = Path(root)
    if not (root_path / "runtime/lib64").is_dir():
        raise RuntimeError(f"Invalid Ascend root, missing runtime/lib64: {root}")

    hccl_lib = _find_hccl(root)
    if not hccl_lib:
        raise RuntimeError(f"Cannot locate libhccl.so under or near: {root}")

    atb_lib = _find_atb_lib_dir(root=root)

    runtime_version = None
    version_file = root_path / "runtime/version.info"
    if version_file.exists():
        raw = version_file.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"([0-9]+(?:\.[0-9A-Za-z]+)+)", raw)
        runtime_version = m.group(1) if m else None

    has_stream_attr = _ascend_has_stream_attr(root)
    legacy_kernel_layout_issue = _detect_broken_legacy_kernel_layout(root)
    current_ld = os.getenv("LD_LIBRARY_PATH", "")

    if _has_active_vendor_ascend_env(root):
        new_ld = current_ld
    else:
        clean_ld = _sanitize_ld_path(current_ld)
        new_ld_parts = _collect_runtime_lib_dirs(root, hccl_lib)
        if atb_lib:
            new_ld_parts.append(atb_lib)
        if clean_ld:
            new_ld_parts.extend([item for item in clean_ld.split(":") if item])
        new_ld_parts = _dedupe_paths(new_ld_parts)
        new_ld = ":".join(new_ld_parts)

    opp_path = f"{root}/opp"
    if legacy_kernel_layout_issue is not None:
        opp_path = _ensure_legacy_kernel_overlay(root)

    exports: dict[str, str] = {
        "ASCEND_HOME_PATH": root,
        "ASCEND_OPP_PATH": opp_path,
        "ASCEND_AICPU_PATH": root,
        "LD_LIBRARY_PATH": new_ld,
        "TORCH_DEVICE_BACKEND_AUTOLOAD": os.getenv("TORCH_DEVICE_BACKEND_AUTOLOAD", "1"),
        "HUST_ASCEND_RUNTIME_VERSION": runtime_version or "",
        "HUST_ASCEND_HAS_STREAM_ATTR": "1" if has_stream_attr else "0",
    }

    if legacy_kernel_layout_issue is not None:
        exports["HUST_ASCEND_OPP_OVERLAY_ROOT"] = opp_path

    atb_set_env = _find_atb_set_env(root=root)
    if atb_set_env:
        exports["HUST_ATB_SET_ENV"] = atb_set_env

    return exports


def build_shell_env_exports(ascend_root: str | None = None) -> str:
    exports = build_env_dict(ascend_root=ascend_root)

    lines: list[str] = []
    for key, val in exports.items():
        lines.append(f"export {key}={shlex.quote(val)}")
    return "\n".join(lines)


def collect_report() -> dict[str, Any]:
    os_release = _read_os_release()
    toolkit = _find_toolkit_root()
    hccl = _find_hccl(toolkit)
    rc, npu_smi_out, _ = _run(["npu-smi", "info"])

    runtime_version = None
    if toolkit:
        version_file = Path(toolkit) / "runtime/version.info"
        if version_file.exists():
            raw = version_file.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"([0-9]+(?:\.[0-9A-Za-z]+)+)", raw)
            runtime_version = m.group(1) if m else None

    atb_set_env = _find_atb_set_env(root=toolkit)
    legacy_kernel_layout_issue = _detect_broken_legacy_kernel_layout(toolkit)
    env_exports = None
    torch_npu_import_ok = False
    torch_npu_import_error = None
    if toolkit:
        try:
            env_exports = build_env_dict(toolkit)
        except RuntimeError as exc:
            torch_npu_import_error = str(exc)
        else:
            torch_npu_import_ok, torch_npu_import_error = _probe_torch_npu_import(env_exports)
    else:
        torch_npu_import_error = "toolkit not found"

    manager_env_opp_path = env_exports["ASCEND_OPP_PATH"] if env_exports else None
    manager_env_uses_opp_overlay = bool(
        env_exports and env_exports.get("HUST_ASCEND_OPP_OVERLAY_ROOT")
    )

    return {
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "os": os_release,
        },
        "ascend": {
            "npu_smi_available": rc == 0,
            "npu_smi_summary": npu_smi_out.splitlines()[:8] if npu_smi_out else [],
            "toolkit_root": toolkit,
            "toolkit_root_exists": bool(toolkit and Path(toolkit).exists()),
            "hccl_lib": hccl,
            "runtime_version": runtime_version,
            "has_aclrt_set_stream_attribute": _ascend_has_stream_attr(toolkit),
            "atb_set_env_exists": atb_set_env is not None,
            "atb_set_env_path": atb_set_env,
            "legacy_kernel_layout_ok": legacy_kernel_layout_issue is None,
            "legacy_kernel_layout_issue": legacy_kernel_layout_issue,
            "manager_env_torch_npu_import_ok": torch_npu_import_ok,
            "manager_env_torch_npu_import_error": torch_npu_import_error,
            "manager_env_opp_path": manager_env_opp_path,
            "manager_env_uses_opp_overlay": manager_env_uses_opp_overlay,
            "manager_env_ld_library_path": env_exports["LD_LIBRARY_PATH"] if env_exports else None,
        },
        "python_stack": {
            "torch": _pip_version("torch"),
            "torch_npu": _pip_version("torch-npu"),
        },
        "recommendations": {
            "target_torch": "2.9.0",
            "target_torch_npu": "2.9.0",
            "target_cann": "8.5.0",
            "npugraph_ready": _ascend_has_stream_attr(toolkit),
        },
    }


def print_human(report: dict[str, Any]) -> None:
    ascend = report["ascend"]
    py = report["python_stack"]
    rec = report["recommendations"]

    print("[doctor] Ascend runtime report")
    print(f"  toolkit_root: {ascend['toolkit_root']}")
    print(f"  runtime_version: {ascend['runtime_version']}")
    print(f"  has_aclrtSetStreamAttribute: {ascend['has_aclrt_set_stream_attribute']}")
    print(f"  npu_smi_available: {ascend['npu_smi_available']}")
    print(f"  legacy_kernel_layout_ok: {ascend['legacy_kernel_layout_ok']}")
    if ascend["legacy_kernel_layout_issue"]:
        print(f"  legacy_kernel_layout_issue: {ascend['legacy_kernel_layout_issue']['message']}")
    print(f"  manager_env_uses_opp_overlay: {ascend['manager_env_uses_opp_overlay']}")
    print(f"  manager_env_opp_path: {ascend['manager_env_opp_path']}")
    print(f"  manager_env_torch_npu_import_ok: {ascend['manager_env_torch_npu_import_ok']}")
    if ascend["manager_env_torch_npu_import_error"]:
        print(f"  manager_env_torch_npu_import_error: {ascend['manager_env_torch_npu_import_error']}")
    print(f"  torch: {py['torch']}")
    print(f"  torch-npu: {py['torch_npu']}")
    print(f"  target torch/torch-npu/cann: {rec['target_torch']}/{rec['target_torch_npu']}/{rec['target_cann']}")


def print_json(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=True, indent=2))
