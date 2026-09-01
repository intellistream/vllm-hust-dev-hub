#!/usr/bin/env python3
"""Validate the Ascend runtime matrix and optionally verify public sources.

The default mode is offline and suitable for unit tests. ``--registry`` proves
that each tag still resolves to the recorded OCI index and ARM64 manifest.
``--links`` checks public HTTPS sources without sending credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "config" / "ascend-official-runtime-matrix.json"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_STATUSES = {
    "official_verified",
    "official_verified_experimental_hardware",
    "community_verified",
    "not_verified",
}
INDEX_ACCEPT = "application/vnd.oci.image.index.v1+json"
MANIFEST_ACCEPT = "application/vnd.oci.image.manifest.v1+json"
USER_AGENT = "vllm-hust-ascend-matrix-verifier/1.0"


class VerificationError(RuntimeError):
    """A deterministic matrix or remote identity check failed."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def request_bytes(
    url: str, *, accept: str | None = None, timeout: int = 30
) -> tuple[bytes, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read(), response.headers


def load_matrix(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_local(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_top = {
        "schema_version",
        "last_verified_at",
        "scope",
        "stack",
        "licenses",
        "sources",
        "runtime_images",
        "known_gaps",
        "known_conflicts",
        "administrator_actions",
    }
    missing_top = sorted(required_top - matrix.keys())
    if missing_top:
        errors.append(f"missing top-level fields: {', '.join(missing_top)}")

    images = matrix.get("runtime_images", [])
    if len(images) != 8:
        errors.append(f"expected 8 current release variants, found {len(images)}")

    ids: set[str] = set()
    tags: set[str] = set()
    required_image = {
        "id",
        "tag",
        "pull_url",
        "immutable_pull_url",
        "index_digest",
        "arm64_manifest_digest",
        "arm64_config_digest",
        "architecture",
        "os",
        "base_image",
        "npu_models",
        "minimum_driver",
        "minimum_firmware",
        "triton_ascend",
        "upstream_verification",
        "vllm_hust_verification",
        "verified_core_commit",
        "verified_plugin_commit",
        "dockerfile_url",
        "install",
        "license",
        "access",
    }
    for image in images:
        item_id = image.get("id", "<missing-id>")
        missing = sorted(required_image - image.keys())
        if missing:
            errors.append(f"{item_id}: missing fields: {', '.join(missing)}")
        if item_id in ids:
            errors.append(f"duplicate id: {item_id}")
        ids.add(item_id)
        tag = image.get("tag")
        if tag in tags:
            errors.append(f"duplicate tag: {tag}")
        tags.add(tag)
        for field in ("index_digest", "arm64_manifest_digest", "arm64_config_digest"):
            value = image.get(field, "")
            if not DIGEST_RE.fullmatch(value):
                errors.append(f"{item_id}: invalid {field}: {value!r}")
        for field in ("verified_core_commit", "verified_plugin_commit"):
            value = image.get(field, "")
            if not COMMIT_RE.fullmatch(value):
                errors.append(f"{item_id}: invalid {field}: {value!r}")
        for field in ("hust_core_commit", "hust_plugin_commit"):
            value = image.get(field)
            if value is not None and not COMMIT_RE.fullmatch(value):
                errors.append(f"{item_id}: invalid {field}: {value!r}")
        for field in ("upstream_verification", "vllm_hust_verification"):
            if image.get(field) not in ALLOWED_STATUSES:
                errors.append(f"{item_id}: invalid {field}: {image.get(field)!r}")
        if image.get("architecture") != "arm64":
            errors.append(f"{item_id}: architecture must be arm64")
        expected_ref = f"quay.io/ascend/vllm-ascend@{image.get('index_digest')}"
        if image.get("immutable_pull_url") != expected_ref:
            errors.append(f"{item_id}: immutable_pull_url does not match index_digest")
        if expected_ref not in image.get("install", ""):
            errors.append(f"{item_id}: install command is not pinned to index_digest")
        if "--platform linux/arm64" not in image.get("install", ""):
            errors.append(f"{item_id}: install command does not select linux/arm64")
        if "310p" in item_id and image.get("triton_ascend") is not None:
            errors.append(f"{item_id}: Triton Ascend must be null for 310P")

    stack = matrix.get("stack", {})
    for field in ("official_core_commit", "official_plugin_commit"):
        if not COMMIT_RE.fullmatch(stack.get(field, "")):
            errors.append(f"stack: invalid {field}")
    return errors


def verify_registry(matrix: dict[str, Any], timeout: int) -> list[str]:
    errors: list[str] = []
    registry = matrix["scope"]["registry"]
    base = f"https://quay.io/v2/{registry.split('/', 1)[1]}"
    for image in matrix["runtime_images"]:
        item_id = image["id"]
        try:
            index_bytes, headers = request_bytes(
                f"{base}/manifests/{image['tag']}", accept=INDEX_ACCEPT, timeout=timeout
            )
            observed_index = headers.get("Docker-Content-Digest") or sha256_bytes(
                index_bytes
            )
            if observed_index != image["index_digest"]:
                errors.append(
                    f"{item_id}: tag digest changed: expected {image['index_digest']}, got {observed_index}"
                )
                continue
            if sha256_bytes(index_bytes) != image["index_digest"]:
                errors.append(
                    f"{item_id}: OCI index bytes do not reproduce index_digest"
                )
            index = json.loads(index_bytes)
            arm64 = [
                item
                for item in index.get("manifests", [])
                if item.get("platform", {}).get("os") == "linux"
                and item.get("platform", {}).get("architecture") == "arm64"
            ]
            if len(arm64) != 1:
                errors.append(
                    f"{item_id}: expected one linux/arm64 manifest, found {len(arm64)}"
                )
                continue
            if arm64[0].get("digest") != image["arm64_manifest_digest"]:
                errors.append(f"{item_id}: ARM64 manifest digest changed")
                continue

            manifest_bytes, manifest_headers = request_bytes(
                f"{base}/manifests/{image['arm64_manifest_digest']}",
                accept=MANIFEST_ACCEPT,
                timeout=timeout,
            )
            observed_manifest = manifest_headers.get(
                "Docker-Content-Digest"
            ) or sha256_bytes(manifest_bytes)
            if observed_manifest != image["arm64_manifest_digest"]:
                errors.append(f"{item_id}: ARM64 manifest response digest mismatch")
                continue
            if sha256_bytes(manifest_bytes) != image["arm64_manifest_digest"]:
                errors.append(
                    f"{item_id}: ARM64 manifest bytes do not reproduce digest"
                )
            manifest = json.loads(manifest_bytes)
            if manifest.get("config", {}).get("digest") != image["arm64_config_digest"]:
                errors.append(f"{item_id}: ARM64 config digest changed")
                continue

            config_bytes, _ = request_bytes(
                f"{base}/blobs/{image['arm64_config_digest']}", timeout=timeout
            )
            if sha256_bytes(config_bytes) != image["arm64_config_digest"]:
                errors.append(f"{item_id}: ARM64 config bytes do not reproduce digest")
                continue
            config = json.loads(config_bytes)
            if config.get("architecture") != "arm64" or config.get("os") != "linux":
                errors.append(f"{item_id}: image config is not linux/arm64")
            print(f"REGISTRY OK  {image['tag']}  {image['index_digest']}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{item_id}: registry check failed: {exc}")
    return errors


def verify_links(matrix: dict[str, Any], timeout: int) -> list[str]:
    errors: list[str] = []
    urls: dict[str, str] = dict(matrix["sources"])
    for image in matrix["runtime_images"]:
        urls[f"dockerfile:{image['id']}"] = image["dockerfile_url"]
    for name, url in sorted(urls.items()):
        if not url.startswith("https://"):
            if name == "hust_a2_openeuler_evidence" and (ROOT / url).is_file():
                print(f"LINK OK      {name}  {url}")
                continue
            errors.append(
                f"{name}: source is neither HTTPS nor an existing repository file: {url}"
            )
            continue
        try:
            _, headers = request_bytes(url, timeout=timeout)
            content_type = headers.get("Content-Type", "unknown")
            print(f"LINK OK      {name}  {content_type}  {url}")
        except urllib.error.HTTPError as exc:
            errors.append(f"{name}: HTTP {exc.code}: {url}")
        except OSError as exc:
            errors.append(f"{name}: link check failed: {exc}: {url}")
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument(
        "--registry", action="store_true", help="verify OCI indexes and ARM64 manifests"
    )
    parser.add_argument(
        "--links", action="store_true", help="download public source pages"
    )
    parser.add_argument(
        "--all", action="store_true", help="run registry and link checks"
    )
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    matrix = load_matrix(args.matrix)
    errors = validate_local(matrix)
    if args.registry or args.all:
        errors.extend(verify_registry(matrix, args.timeout))
    if args.links or args.all:
        errors.extend(verify_links(matrix, args.timeout))
    if errors:
        for error in errors:
            print(f"ERROR         {error}", file=sys.stderr)
        print(f"FAILED: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {len(matrix['runtime_images'])} runtime image records verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
