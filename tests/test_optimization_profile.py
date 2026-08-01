from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = REPO_ROOT / "scripts" / "optimization_profile.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "optimization_manifests"


def resolve(name: str, *parameters: str, env: dict[str, str] | None = None):
    command = [
        sys.executable,
        str(RESOLVER),
        "--manifest",
        str(FIXTURES / f"{name}.json"),
        "--format",
        "json",
    ]
    for parameter in parameters:
        command.extend(("--param", parameter))
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return result, json.loads(result.stdout) if result.returncode == 0 else None


def test_bidkv_profile_hides_entrypoint_and_json_plumbing() -> None:
    result, environment = resolve("bidkv")

    assert result.returncode == 0
    assert environment["VLLM_OPTIMIZATION_ENTRYPOINT_GROUP"] == "vllm.victim_selector"
    assert environment["VLLM_OPTIMIZATION_PLUGIN"] == "bidkv"
    assert environment["BIDKV_UTILITY_ENABLE"] == "1"
    assert environment["VLLM_PLUGINS"] == "ascend"
    args = json.loads(environment["VLLM_ENGINE_EXTRA_ARGS_JSON"])
    assert args[0] == "--additional-config"
    assert json.loads(args[1])["victim_selector_plugin"] == "bidkv"


def test_diffspec_requires_and_renders_draft_model() -> None:
    missing, _environment = resolve("diffspec")
    assert missing.returncode != 0
    assert "requires --draft-model" in missing.stderr

    result, environment = resolve("diffspec", "draft_model=/models/eagle3")
    assert result.returncode == 0
    args = json.loads(environment["VLLM_ENGINE_EXTRA_ARGS_JSON"])
    assert json.loads(args[1])["model"] == "/models/eagle3"
    assert environment["VLLM_ENGINE_ENFORCE_EAGER"] == "1"
    assert environment["VLLM_PLUGINS"] == "ascend,diffspec"


def test_latchmoe_uses_default_or_explicit_offload_budget() -> None:
    default_result, default_environment = resolve("latchmoe")
    assert default_result.returncode == 0
    assert default_environment["VLLM_ASCEND_MOE_OFFLOAD_GB"] == "14"

    result, environment = resolve("latchmoe", "offload_gb=28")
    assert result.returncode == 0
    assert environment["VLLM_ASCEND_MOE_OFFLOAD_GB"] == "28"
    assert environment["VLLM_PLUGINS"] == "ascend,moe_offload_ascend"


def test_operator_environment_overrides_manifest_defaults() -> None:
    env = os.environ.copy()
    env["BIDKV_UTILITY_ENABLE"] = "0"
    result, environment = resolve("bidkv", env=env)

    assert result.returncode == 0
    assert environment["BIDKV_UTILITY_ENABLE"] == "0"


def test_multiple_profiles_fail_closed() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            "--profile",
            "bidkv,diffspec",
            "--workspace-root",
            str(FIXTURES.parent),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "multiple optimization profiles are not supported" in result.stderr
