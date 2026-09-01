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
    assert lock["python_stack"] == {
        "torch": "2.10.0+cpu",
        "torch_npu": "2.10.0.post4",
        "triton_ascend": "3.2.2",
        "vllm_ascend": "0.23.0",
    }
    assert lock["runtime"]["cann"] == "9.1.0"
    assert lock["runtime"]["graph_mode"] is True


def test_locked_image_and_launcher_enforce_identity() -> None:
    dockerfile = (ROOT / "images/vllm-ascend-production/Dockerfile").read_text()
    builder = (ROOT / "scripts/build_locked_vllm_ascend_image.sh").read_text()
    launcher = (ROOT / "scripts/run_vllm_hust_engine.sh").read_text()

    assert "ARG BASE_IMAGE" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile
    assert "ai.vllm-hust.vllm-core.commit" in dockerfile
    assert "ai.vllm-hust.vllm-ascend.commit" in dockerfile
    assert "git -C \"$root\" status --porcelain" in builder
    assert "--pull=false" in builder
    assert 'expected_image_id="${VLLM_ENGINE_EXPECTED_IMAGE_ID:-}"' in launcher
    assert "image identity mismatch" in launcher
    assert "runs $running_image_id, expected $expected_image_id" in launcher
