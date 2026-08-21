from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

EXCLUDED_DIRS = {".cache", ".git", ".hf-home", "__pycache__"}
METADATA_ONLY_ASSETS = {"workload-generators"}
FAILED_MARKERS = (".partial", ".failed", ".incomplete")


def is_failed_artifact(name: str) -> bool:
    return any(marker in name for marker in FAILED_MARKERS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_binary_lines(handle: BinaryIO) -> int:
    count = 0
    for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
        count += block.count(b"\n")
    return count


def record_count(path: Path) -> int | None:
    suffixes = path.suffixes
    if path.suffix == ".parquet":
        from pyarrow import parquet

        return parquet.ParquetFile(path).metadata.num_rows
    if suffixes[-2:] == [".jsonl", ".gz"]:
        with gzip.open(path, "rb") as handle:
            return count_binary_lines(handle)
    if path.suffix == ".jsonl":
        with path.open("rb") as handle:
            return count_binary_lines(handle)
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)
    return None


def iter_files(root: Path, link_scope_root: Path | None = None):
    resolved_root = (link_scope_root or root).resolve()
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            d
            for d in directories
            if d not in EXCLUDED_DIRS and not (Path(current) / d).is_symlink()
        )
        for name in sorted(files):
            path = Path(current) / name
            # Count external files intentionally exposed through the canonical
            # asset root, but do not double-count an internal alias of a file that
            # is already under the same asset directory.
            if path.is_symlink():
                target = path.resolve()
                if not target.is_file() or target == resolved_root or resolved_root in target.parents:
                    continue
            if is_failed_artifact(name):
                continue
            yield path


def inspect_asset(path: Path, link_scope_root: Path | None = None) -> dict[str, Any]:
    if path.is_file():
        paths = [path]
        base = path.parent
    else:
        paths = list(iter_files(path, link_scope_root))
        base = path
    files: list[dict[str, Any]] = []
    for item in paths:
        entry: dict[str, Any] = {
            "path": str(item.relative_to(base)),
            "size": item.stat().st_size,
            "sha256": sha256(item),
        }
        if item.is_symlink():
            entry["symlink_target"] = str(item.resolve())
        try:
            rows = record_count(item)
        except Exception as error:  # noqa: BLE001 - inventory must retain every parse failure.
            entry["read_error"] = f"{type(error).__name__}: {error}"
        else:
            if rows is not None:
                entry["records"] = rows
        files.append(entry)
    return {
        "path": str(path),
        "file_count": len(files),
        "total_size": sum(item["size"] for item in files),
        "files": files,
    }


def load_logical_assets(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and verify logical assets without copying their physical payloads."""
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise TypeError("logical asset manifest must contain an assets list")

    seen_ids: set[str] = set()
    seen_physical_paths: dict[str, str] = {}
    verified: list[dict[str, Any]] = []
    for asset in assets:
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            raise ValueError("every logical asset must have a non-empty asset_id")
        if asset_id in seen_ids:
            raise ValueError(f"duplicate logical asset_id: {asset_id}")
        seen_ids.add(asset_id)

        physical = asset.get("physical_file")
        if not isinstance(physical, dict):
            raise TypeError(f"{asset_id}: physical_file must be an object")
        source = Path(physical.get("path", ""))
        if not source.is_file():
            raise ValueError(f"{asset_id}: physical file is missing: {source}")
        resolved = str(source.resolve())
        if resolved in seen_physical_paths:
            raise ValueError(
                f"{asset_id}: physical file is already owned by "
                f"{seen_physical_paths[resolved]}: {resolved}"
            )
        seen_physical_paths[resolved] = asset_id

        actual_size = source.stat().st_size
        expected_size = physical.get("size")
        if actual_size != expected_size:
            raise ValueError(
                f"{asset_id}: size mismatch: expected {expected_size}, got {actual_size}"
            )
        actual_sha256 = sha256(source)
        expected_sha256 = physical.get("sha256")
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"{asset_id}: SHA-256 mismatch: expected {expected_sha256}, "
                f"got {actual_sha256}"
            )
        expected_records = physical.get("records")
        actual_records = record_count(source)
        if expected_records is not None and actual_records != expected_records:
            raise ValueError(
                f"{asset_id}: record count mismatch: expected {expected_records}, "
                f"got {actual_records}"
            )

        stat = source.stat()
        item = json.loads(json.dumps(asset))
        item["physical_file"].update(
            {
                "resolved_path": resolved,
                "device": stat.st_dev,
                "inode": stat.st_ino,
                "verification": "SHA256_SIZE_RECORD_COUNT_VERIFIED",
            }
        )
        verified.append(item)

    manifest_identity = {
        "path": str(manifest_path.resolve()),
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "inventory_version": manifest.get("inventory_version"),
        "test_plan": manifest.get("test_plan"),
        "dataset_policy": manifest.get("dataset_policy"),
        "normalization_contract": manifest.get("normalization_contract"),
    }
    return manifest_identity, verified


def build_inventory(root: Path) -> dict[str, Any]:
    assets = []
    failed_artifacts = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name in EXCLUDED_DIRS:
            continue
        if is_failed_artifact(path.name):
            failed_artifacts.append(
                {"path": str(path), "size": path.stat().st_size if path.is_file() else None}
            )
            continue
        if path.name in METADATA_ONLY_ASSETS:
            links = []
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                links.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "symlink_target": str(child.resolve()) if child.is_symlink() else None,
                    }
                )
            assets.append(
                {
                    "asset": path.name,
                    "path": str(path),
                    "inventory_mode": "metadata_only",
                    "reason": "Generator source trees are frozen separately; they are not dataset payloads.",
                    "links": links,
                    "file_count": 0,
                    "total_size": 0,
                    "files": [],
                }
            )
            continue
        assets.append({"asset": path.name, **inspect_asset(path, root)})
    read_error_count = sum(
        1
        for asset in assets
        for file_entry in asset["files"]
        if "read_error" in file_entry
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization": "A1-A4",
        "asset_root": str(root.resolve()),
        "status": (
            "INVENTORIED_WITH_BLOCKERS"
            if failed_artifacts or read_error_count
            else "ASSET_INVENTORY_VERIFIED"
        ),
        "asset_count": len(assets),
        "file_count": sum(item["file_count"] for item in assets),
        "total_size": sum(item["total_size"] for item in assets),
        "failed_artifacts": failed_artifacts,
        "read_error_count": read_error_count,
        "assets": assets,
    }


def extend_inventory(
    inventory: dict[str, Any], logical_manifest_path: Path
) -> dict[str, Any]:
    manifest, logical_assets = load_logical_assets(logical_manifest_path)
    result = json.loads(json.dumps(inventory))
    result["schema_version"] = 2
    result["inventory_version"] = manifest["inventory_version"]
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["logical_asset_manifest"] = manifest
    result["logical_asset_count"] = len(logical_assets)
    result["logical_assets"] = logical_assets
    result["physical_storage_policy"] = {
        "mode": "single_physical_file_with_manifest_references",
        "duplicate_physical_path_count": 0,
        "duplicate_content_sha256_count": len(logical_assets)
        - len({asset["physical_file"]["sha256"] for asset in logical_assets}),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path)
    source.add_argument("--base-inventory", type=Path)
    parser.add_argument("--logical-manifest", type=Path)
    parser.add_argument("--inventory-version")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.base_inventory:
        result = json.loads(args.base_inventory.read_text())
    else:
        result = build_inventory(args.root)
    if args.logical_manifest:
        result = extend_inventory(result, args.logical_manifest)
    if args.inventory_version:
        result["inventory_version"] = args.inventory_version
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "asset_count": result["asset_count"],
                "file_count": result["file_count"],
                "total_size": result["total_size"],
                "logical_asset_count": result.get("logical_asset_count", 0),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
