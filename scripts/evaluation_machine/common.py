from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TARGET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PRIORITIES = {"release": 0, "required": 10, "normal": 20, "diagnostic": 30}


class ContractError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_signature(
    secret: bytes, timestamp: str, body: bytes, signature: str
) -> None:
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise ContractError("invalid request timestamp") from exc
    if abs(int(time.time()) - request_time) > 300:
        raise ContractError("request timestamp is outside the 5 minute window")
    expected = hmac.new(secret, timestamp.encode() + b"\n" + body, hashlib.sha256)
    supplied = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected.hexdigest(), supplied):
        raise ContractError("invalid request signature")


def validate_request(
    payload: dict[str, Any], allowed_repositories: set[str]
) -> dict[str, Any]:
    required = {
        "schema_version",
        "repository",
        "core_commit",
        "plugin_repository",
        "plugin_commit",
        "target_id",
        "target_registry_version",
        "repeat_count",
        "npu_count",
        "priority",
        "requested_by",
        "source_url",
    }
    unknown = set(payload) - (required | {"metadata"})
    missing = required - set(payload)
    if missing:
        raise ContractError(f"missing request fields: {sorted(missing)}")
    if unknown:
        raise ContractError(f"unknown request fields: {sorted(unknown)}")
    if payload["schema_version"] != 1:
        raise ContractError("schema_version must be 1")
    repository = payload["repository"]
    plugin_repository = payload["plugin_repository"]
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise ContractError("invalid repository")
    if not isinstance(plugin_repository, str) or not REPOSITORY_RE.fullmatch(
        plugin_repository
    ):
        raise ContractError("invalid plugin_repository")
    if (
        repository not in allowed_repositories
        or plugin_repository not in allowed_repositories
    ):
        raise ContractError("repository is not allowlisted")
    for field in ("core_commit", "plugin_commit"):
        value = payload[field]
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise ContractError(f"{field} must be a full lowercase commit SHA")
    target_id = payload["target_id"]
    if not isinstance(target_id, str) or not TARGET_RE.fullmatch(target_id):
        raise ContractError("invalid target_id")
    registry_version = payload["target_registry_version"]
    if not isinstance(registry_version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", registry_version
    ):
        raise ContractError("target_registry_version must be semantic x.y.z")
    repeats = payload["repeat_count"]
    if (
        not isinstance(repeats, int)
        or isinstance(repeats, bool)
        or not 3 <= repeats <= 9
    ):
        raise ContractError("repeat_count must be between 3 and 9")
    npu_count = payload["npu_count"]
    if (
        not isinstance(npu_count, int)
        or isinstance(npu_count, bool)
        or not 1 <= npu_count <= 64
    ):
        raise ContractError("npu_count must be between 1 and 64")
    if payload["priority"] not in PRIORITIES:
        raise ContractError(f"priority must be one of {sorted(PRIORITIES)}")
    for field in ("requested_by", "source_url"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ContractError(f"{field} must be a non-empty string")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ContractError("metadata must be an object")
    return json.loads(canonical_json(payload))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ContractError(f"expected object in {path}")
    return value
