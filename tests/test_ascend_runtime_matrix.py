import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ascend_runtime_matrix.py"
SPEC = importlib.util.spec_from_file_location("verify_ascend_runtime_matrix", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_runtime_matrix_is_complete_and_valid():
    matrix = json.loads(
        (ROOT / "config" / "ascend-official-runtime-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    assert MODULE.validate_local(matrix) == []
    assert {item["tag"] for item in matrix["runtime_images"]} == {
        "v0.23.0",
        "v0.23.0-openeuler",
        "v0.23.0-a3",
        "v0.23.0-a3-openeuler",
        "v0.23.0-a5",
        "v0.23.0-a5-openeuler",
        "v0.23.0-310p",
        "v0.23.0-310p-openeuler",
    }


def test_only_community_verified_record_has_hust_commits():
    matrix = MODULE.load_matrix(MODULE.DEFAULT_MATRIX)
    verified = [
        item
        for item in matrix["runtime_images"]
        if item["vllm_hust_verification"] == "community_verified"
    ]
    assert [item["id"] for item in verified] == ["a2-openeuler24.03-arm64"]
    assert verified[0]["hust_core_commit"]
    assert verified[0]["hust_plugin_commit"]
