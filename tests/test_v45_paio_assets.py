import hashlib
import json
from pathlib import Path

import pytest

from scripts.evaluation_machine.inventory_a1_a4_assets import (
    extend_inventory,
    inspect_asset,
    load_logical_assets,
)

MANIFEST = Path("config/v4.5-paio-cloud-dataset-assets.json")
ADMISSION_RECEIPT = Path("docs/v4.5-paio-cloud-asset-admission.md")


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_v45_paio_manifest_has_eight_unique_single_file_assets() -> None:
    manifest = load_manifest()
    assets = manifest["assets"]
    assert manifest["inventory_version"] == "V4.5-PAIO-CLOUD-20260821.3"
    assert manifest["test_plan"]["sha256"] == (
        "aa65cd885aa9254095855f2a196e0875680d19eeb9fd427ffafa31c9ac6830c4"
    )
    assert {asset["asset_id"] for asset in assets} == {
        "PAIO-CHAT-1000",
        "PAIO-CODE-EVAL-1000",
        "PAIO-JSON-500",
        "PAIO-LONG-PREFILL-5000",
        "PAIO-PREFIX-SHARED-5000",
        "PAIO-REUSE-CONV-5000",
        "PAIO-SEMANTIC-SIMILAR-5000",
        "PAIO-LONGTEXT-4000",
    }
    assert len({asset["physical_file"]["path"] for asset in assets}) == 8
    assert len({asset["physical_file"]["sha256"] for asset in assets}) == 8


def test_v45_admission_receipt_binds_the_logical_manifest() -> None:
    manifest_sha256 = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    receipt = ADMISSION_RECEIPT.read_text()
    assert manifest_sha256 == (
        "c9e0ee43dc7abacadc6cddca88df5d5b5f0114b97f25c644b527dcb2d9370a81"
    )
    assert manifest_sha256 in receipt
    assert "43c7dd8f96c66c70c3623cf2413d06442d33aa68aef58f2fe9a4b8f762737db6" in receipt


def test_v45_paio_references_preserve_scope_and_contract_boundaries() -> None:
    assets = {asset["asset_id"]: asset for asset in load_manifest()["assets"]}

    def references(asset_id: str) -> set[tuple[str, str, str]]:
        return {
            (ref["scope"], ref["metric_configuration"], ref["cell_or_tenant"])
            for ref in assets[asset_id]["references"]
        }

    assert references("PAIO-CHAT-1000") == {
        ("A2", "A2-DIALOGUE-FP16-PC", "dialogue_multiturn"),
        ("A4", "A4-MT-FP16-PC", "dialogue"),
    }
    assert ("A2", "A2-REASON-FP16", "reasoning_ttft") in references(
        "PAIO-CODE-EVAL-1000"
    )
    assert "tool_calling" in assets["PAIO-CODE-EVAL-1000"][
        "forbidden_classification"
    ]
    assert ("A3", "A3-32K-FP16", "30720_input_2048_output_cap") in references(
        "PAIO-LONGTEXT-4000"
    )
    assert "A3_30720_input_gate" in assets["PAIO-LONG-PREFILL-5000"][
        "forbidden_classification"
    ]
    assert all(
        ref["contract_role"] == "non_gate_extension"
        for ref in assets["PAIO-SEMANTIC-SIMILAR-5000"]["references"]
    )


def test_v45_paio_policy_has_no_dataset_priority_hierarchy() -> None:
    manifest = load_manifest()
    assert manifest["dataset_policy"] == {
        "organization": "metric_configuration_dataset_groups",
        "dataset_hierarchy": "none",
        "single_prescribed_dataset": False,
        "reporting": "report_each_dataset_separately_without_weighted_average",
        "physical_storage": "one_physical_file_per_content_with_cross_scope_manifest_references",
        "canonical_asset_root": "/data/shared_datasets/vllm-hust-evaluation/a1-a4/assets",
        "source_package_receipt_root": "/data/shared_datasets/vllm-hust-evaluation/a1-a4/assets/paio-cloud/20260820",
        "scope_view_root": "/data/shared_datasets/vllm-hust-evaluation/a1-a4/by-scope",
        "formal_measurement": "inactive_until_all_contract_qualifications_are_satisfied",
    }
    assert manifest["package_boundaries"]["contains_tools_field"] is False
    assert manifest["package_boundaries"]["may_replace_bfcl_or_tau2"] is False
    assert manifest["package_boundaries"]["contains_visual_input"] is False
    assert manifest["package_boundaries"]["may_replace_visionarena"] is False


def test_logical_asset_loader_verifies_file_and_rejects_duplicate_ownership(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "asset.jsonl"
    payload.write_text('{"id": 1}\n')
    physical = {
        "path": str(payload),
        "records": 1,
        "size": payload.stat().st_size,
        "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
    }
    manifest = {
        "inventory_version": "test-v1",
        "assets": [{"asset_id": "ONE", "physical_file": physical, "references": []}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    identity, verified = load_logical_assets(manifest_path)
    assert identity["inventory_version"] == "test-v1"
    assert verified[0]["physical_file"]["verification"] == (
        "SHA256_SIZE_RECORD_COUNT_VERIFIED"
    )
    extended = extend_inventory(
        {"schema_version": 1, "generated_at": "old", "assets": []}, manifest_path
    )
    assert extended["schema_version"] == 2
    assert extended["logical_asset_count"] == 1
    assert extended["physical_storage_policy"]["duplicate_physical_path_count"] == 0

    manifest["assets"].append(
        {"asset_id": "TWO", "physical_file": physical, "references": []}
    )
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="physical file is already owned"):
        load_logical_assets(manifest_path)


def test_physical_inventory_does_not_count_internal_symlink_views(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical.jsonl"
    physical.write_text('{"id": 1}\n')
    aliases = tmp_path / "aliases"
    aliases.mkdir()
    (aliases / "view.jsonl").symlink_to(physical)
    inspected = inspect_asset(tmp_path)
    assert inspected["file_count"] == 1
    assert inspected["files"][0]["path"] == "physical.jsonl"


def test_physical_inventory_counts_external_dataset_symlinks(tmp_path: Path) -> None:
    external = tmp_path / "external.jsonl"
    external.write_text('{"id": 1}\n')
    asset = tmp_path / "asset"
    asset.mkdir()
    (asset / "view.jsonl").symlink_to(external)

    inspected = inspect_asset(asset)

    assert inspected["file_count"] == 1
    assert inspected["files"][0]["path"] == "view.jsonl"
    assert inspected["files"][0]["symlink_target"] == str(external)


def test_physical_inventory_skips_aliases_elsewhere_in_canonical_root(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical.jsonl"
    physical.write_text('{"id": 1}\n')
    alias_asset = tmp_path / "alias-asset"
    alias_asset.mkdir()
    (alias_asset / "view.jsonl").symlink_to(physical)

    inspected = inspect_asset(alias_asset, link_scope_root=tmp_path)

    assert inspected["file_count"] == 0
