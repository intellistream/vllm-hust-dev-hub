from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from scripts.evaluation_machine.common import (
    ContractError,
    canonical_json,
    validate_request,
    verify_signature,
)
from scripts.evaluation_machine.server import EvaluationServer
from scripts.evaluation_machine.store import JobStore
from scripts.evaluation_machine.worker import parse_busy_npus


def valid_request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": "vLLM-HUST/vllm-hust",
        "core_commit": "a" * 40,
        "plugin_repository": "vLLM-HUST/vllm-ascend-hust",
        "plugin_commit": "b" * 40,
        "target_id": "official-random-online",
        "target_registry_version": "1.3.6",
        "repeat_count": 3,
        "npu_count": 1,
        "priority": "required",
        "requested_by": "octocat",
        "source_url": "https://github.com/vLLM-HUST/vllm-hust/actions/runs/1",
        "metadata": {"pull_request": 123},
    }


def test_request_contract_accepts_exact_identity() -> None:
    request = valid_request()
    assert validate_request(
        request, {"vLLM-HUST/vllm-hust", "vLLM-HUST/vllm-ascend-hust"}
    ) == json.loads(canonical_json(request))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("core_commit", "main"),
        ("repeat_count", 1),
        ("npu_count", 0),
        ("target_registry_version", "latest"),
        ("priority", "urgent"),
    ],
)
def test_request_contract_fails_closed(field: str, value: object) -> None:
    request = valid_request()
    request[field] = value
    with pytest.raises(ContractError):
        validate_request(request, {"vLLM-HUST/vllm-hust", "vLLM-HUST/vllm-ascend-hust"})


def test_signature_rejects_tamper() -> None:
    import hashlib
    import hmac

    timestamp = str(int(time.time()))
    body = canonical_json(valid_request())
    signature = hmac.new(b"secret", timestamp.encode() + b"\n" + body, hashlib.sha256)
    verify_signature(b"secret", timestamp, body, signature.hexdigest())
    with pytest.raises(ContractError, match="signature"):
        verify_signature(b"secret", timestamp, body + b"x", signature.hexdigest())


def test_store_idempotency_and_claim(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "queue.sqlite3")
    first, created = store.submit("repo:run:attempt:target", valid_request())
    second, repeated = store.submit("repo:run:attempt:target", valid_request())
    assert created is True
    assert repeated is False
    assert first["id"] == second["id"]
    assert store.next_queued()["id"] == first["id"]  # type: ignore[index]
    claimed = store.claim(first["id"], "worker-1", [1])
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["assigned_npus"] == "[1]"


def test_store_rejects_idempotency_payload_change(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "queue.sqlite3")
    store.submit("repo:run:attempt:target", valid_request())
    changed = valid_request()
    changed["core_commit"] = "c" * 40
    with pytest.raises(ValueError, match="idempotency"):
        store.submit("repo:run:attempt:target", changed)


def test_parse_busy_npus_uses_process_table_only() -> None:
    output = """
| NPU     Chip | Process id | Process name | Process memory(MB) |
| No running processes found in NPU 0 |
| 1       0    | 12345      | VLLMEngineCor | 36961 |
| No running processes found in NPU 2 |
| 7       0    | 67890      | python3       | 1234 |
"""
    assert parse_busy_npus(output) == {1, 7}


def test_api_submission_is_authenticated_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_EVALUATION_TOKEN", "token")
    monkeypatch.setenv("TEST_EVALUATION_SECRET", "secret")
    config = {
        "state_dir": str(tmp_path),
        "allowed_repositories": [
            "vLLM-HUST/vllm-hust",
            "vLLM-HUST/vllm-ascend-hust",
        ],
        "token_env": "TEST_EVALUATION_TOKEN",
        "hmac_secret_env": "TEST_EVALUATION_SECRET",
    }
    server = EvaluationServer(("127.0.0.1", 0), config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = canonical_json(valid_request())
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"secret", timestamp.encode() + b"\n" + body, hashlib.sha256
        ).hexdigest()
        headers = {
            "Authorization": "Bearer token",
            "X-Evaluation-Timestamp": timestamp,
            "X-Evaluation-Signature": f"sha256={signature}",
            "Idempotency-Key": "repo:run:attempt:target",
            "Content-Type": "application/json",
        }
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/jobs"
        first = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(url, body, headers, method="POST")
            ).read()
        )
        second = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(url, body, headers, method="POST")
            ).read()
        )
        assert first["id"] == second["id"]
        assert first["status"] == "queued"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
