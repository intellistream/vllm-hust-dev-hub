import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_runtime_lock_is_complete_and_immutable() -> None:
    lock = json.loads((ROOT / "config/vllm-ascend-production-lock.json").read_text())

    assert lock["schema"] == "vllm-hust.production-runtime-lock/v1"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", lock["base_image"]["digest"])
    assert re.fullmatch(r"[0-9a-f]{40}", lock["vllm_core"]["commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", lock["vllm_ascend"]["commit"])
    assert lock["vllm_core"]["repository"] == "git@github.com:vLLM-HUST/vllm-hust.git"
    assert lock["vllm_ascend"]["repository"] == "git@github.com:vLLM-HUST/vllm-ascend-hust.git"
    assert lock["vllm_core"]["source_version"].endswith(
        lock["vllm_core"]["commit"][:8]
    )
    assert lock["vllm_ascend"]["source_version"].endswith(
        lock["vllm_ascend"]["commit"][:9]
    )
    assert lock["compatibility"] == {
        "runtime_base": "vLLM-Ascend 0.23.0",
        "vllm_api": "0.23.1rc0",
        "cann": "9.1.0",
        "torch_npu": "2.10.0.post4",
    }
    assert lock["python_stack"] == {
        "torch": "2.10.0+cpu",
        "torch_npu": "2.10.0.post4",
        "triton_ascend": "3.2.2",
        "vllm_base": "0.23.0+empty",
        "vllm_ascend": "0.23.0",
    }
    assert lock["runtime"]["cann"] == "9.1.0"
    assert lock["runtime"]["graph_mode"] is True


def test_locked_image_and_launcher_enforce_identity() -> None:
    dockerfile = (ROOT / "images/vllm-ascend-production/Dockerfile").read_text()
    metadata_installer = (
        ROOT / "images/vllm-ascend-production/install_runtime_metadata.py"
    ).read_text()
    builder = (ROOT / "scripts/build_locked_vllm_ascend_image.sh").read_text()
    launcher = (ROOT / "scripts/run_vllm_hust_engine.sh").read_text()

    assert "ARG BASE_IMAGE" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile
    assert "ai.vllm-hust.vllm-core.commit" in dockerfile
    assert "ai.vllm-hust.vllm-ascend.commit" in dockerfile
    assert "ai.vllm-hust.compatibility.base" in dockerfile
    assert "install_runtime_metadata.py" in dockerfile
    assert 'assert "ascend" in platform' in dockerfile
    assert "shutil.copytree(source, target)" in metadata_installer
    assert "TORCH_DEVICE_BACKEND_AUTOLOAD=0 python3" in dockerfile
    assert "git -C \"$root\" status --porcelain" in builder
    assert "plugin verifies core=" in builder
    assert "--pull=false" in builder
    assert 'expected_image_id="${VLLM_ENGINE_EXPECTED_IMAGE_ID:-}"' in launcher
    assert "image identity mismatch" in launcher
    assert "runs $running_image_id, expected $expected_image_id" in launcher
