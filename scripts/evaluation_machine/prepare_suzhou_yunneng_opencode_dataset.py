from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from pyarrow import parquet

SOURCE_DATASET = "princeton-nlp/SWE-bench_Verified"
SOURCE_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def task_prompt(task: dict[str, Any]) -> str:
    return (
        "Resolve the following real open-source issue in the checked-out repository.\n"
        "Work only from the issue statement and repository state at the frozen base commit.\n"
        "Inspect the code, implement the smallest correct fix, and run relevant tests.\n"
        "Do not look up or reconstruct the reference patch. Preserve all failed attempts.\n\n"
        f"Repository: {task['repo']}\n"
        f"Base commit: {task['base_commit']}\n"
        f"Issue instance: {task['instance_id']}\n\n"
        f"Issue statement:\n{task['problem_statement']}"
    )


def build(source: Path, output: Path) -> dict[str, Any]:
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = parquet.read_table(source).to_pylist()
    tasks = []
    hidden_oracles = []
    for row in rows:
        statement = normalized_text(row["problem_statement"])
        identity_material = "\0".join(
            (SOURCE_REVISION, row["instance_id"], row["base_commit"], statement)
        ).encode()
        case_key = sha256_bytes(identity_material)
        task = {
            "case_key": case_key,
            "instance_id": row["instance_id"],
            "repo": row["repo"],
            "base_commit": row["base_commit"],
            "environment_setup_commit": row["environment_setup_commit"],
            "version": row["version"],
            "created_at": row["created_at"],
            "difficulty": row["difficulty"],
            "problem_statement": statement,
            "problem_statement_sha256": sha256_bytes(statement.encode()),
        }
        prompt = task_prompt(task)
        task["opencode_prompt"] = prompt
        task["opencode_prompt_sha256"] = sha256_bytes(prompt.encode())
        tasks.append(task)
        hidden_oracles.append(
            {
                "case_key": case_key,
                "instance_id": row["instance_id"],
                "gold_patch_sha256": sha256_bytes(
                    normalized_text(row["patch"]).encode()
                ),
                "test_patch_sha256": sha256_bytes(
                    normalized_text(row["test_patch"]).encode()
                ),
                "fail_to_pass_sha256": sha256_bytes(
                    normalized_text(row["FAIL_TO_PASS"]).encode()
                ),
                "pass_to_pass_sha256": sha256_bytes(
                    normalized_text(row["PASS_TO_PASS"]).encode()
                ),
            }
        )

    tasks.sort(key=lambda item: item["case_key"])
    hidden_oracles.sort(key=lambda item: item["case_key"])
    output.mkdir(parents=True, exist_ok=True)
    task_bytes = b"".join(canonical_json(item) + b"\n" for item in tasks)
    oracle_bytes = canonical_json(hidden_oracles) + b"\n"
    (output / "ordered-tasks.jsonl").write_bytes(task_bytes)
    (output / "hidden-oracle-hashes.json").write_bytes(oracle_bytes)

    repo_counts: dict[str, int] = {}
    for task in tasks:
        repo_counts[task["repo"]] = repo_counts.get(task["repo"], 0) + 1
    manifest = {
        "schema_version": 1,
        "asset_id": "SZYN-OPENCODE-SWEBENCH-VERIFIED-500",
        "display_name": "苏州云能 OpenCode 开源 Issue 解决生产优化数据集",
        "producer": "苏州云能",
        "production_use": "LLM_serving_and_agent_workload_optimization",
        "source_kind": "real_open_source_issue_with_generated_agent_execution_trace",
        "not_claimed_as": [
            "Suzhou_Yunneng_original_issue_content",
            "Suzhou_Yunneng_real_online_traffic",
            "A1_to_A4_hard_gate_replacement",
        ],
        "source": {
            "dataset": SOURCE_DATASET,
            "revision": SOURCE_REVISION,
            "source_file_sha256": source_sha256,
            "license_policy": "retain_each_upstream_repository_license_and_dataset_provenance",
        },
        "selection": {
            "rule": "all_500_cases_sorted_by_case_key",
            "case_key": "sha256(dataset_revision||instance_id||base_commit||normalized_problem_statement)",
            "case_count": len(tasks),
            "repo_counts": dict(sorted(repo_counts.items())),
        },
        "files": {
            "ordered_tasks": {
                "path": "ordered-tasks.jsonl",
                "sha256": sha256_bytes(task_bytes),
            },
            "hidden_oracle_hashes": {
                "path": "hidden-oracle-hashes.json",
                "sha256": sha256_bytes(oracle_bytes),
            },
        },
        "execution_policy": {
            "gold_not_exposed_to_opencode": True,
            "retain_success_failure_timeout_and_retry": True,
            "collection_model_is_part_of_dataset_version": True,
            "formal_execution_status": "INACTIVE_UNTIL_MODEL_AND_SANDBOX_CONTRACT_FROZEN",
        },
    }
    manifest_bytes = canonical_json(manifest) + b"\n"
    (output / "manifest.json").write_bytes(manifest_bytes)
    return {
        "task_count": len(tasks),
        "ordered_tasks_sha256": sha256_bytes(task_bytes),
        "hidden_oracle_hashes_sha256": sha256_bytes(oracle_bytes),
        "manifest_sha256": sha256_bytes(manifest_bytes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
