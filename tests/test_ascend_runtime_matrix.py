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


def test_upstream_rebuild_invalidates_pre_rebuild_community_status():
    matrix = MODULE.load_matrix(MODULE.DEFAULT_MATRIX)
    assert (
        matrix["repository_identity"]["core"]["rebuild_source"] == "official_upstream"
    )
    assert (
        matrix["repository_identity"]["plugin"]["rebuild_source"] == "official_upstream"
    )
    assert all(
        item["vllm_hust_verification"] == "not_verified"
        for item in matrix["runtime_images"]
    )
    a2_openeuler = next(
        item
        for item in matrix["runtime_images"]
        if item["id"] == "a2-openeuler24.03-arm64"
    )
    assert a2_openeuler["hust_core_commit"] is None
    assert a2_openeuler["hust_plugin_commit"] is None
    assert a2_openeuler["historical_evidence"]["status"] == "pre_rebuild_not_current"
