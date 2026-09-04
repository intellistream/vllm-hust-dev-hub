from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = REPO_ROOT / "scripts" / "optimization_profile.py"
CONTAINER_EXPORTS = REPO_ROOT / "scripts" / "container_env_exports.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "optimization_manifests"


def resolve(
    name: str,
    *parameters: str,
    env: dict[str, str] | None = None,
    container_repo: str | None = None,
):
    command = [
        sys.executable,
        str(RESOLVER),
        "--manifest",
        str(FIXTURES / f"{name}.json"),
        "--format",
        "json",
    ]
    if container_repo is not None:
        command.extend(("--container-repo", container_repo))
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
    assert environment["VLLM_OPTIMIZATION_ENTRYPOINT_GROUP"] == "vllm_hust.extension_bundles"
    assert environment["VLLM_OPTIMIZATION_PLUGIN"] == "org.vllm-hust.bidkv"
    assert environment["BIDKV_UTILITY_ENABLE"] == "1"
    assert environment["VLLM_PLUGINS"] == "ascend"
    args = json.loads(environment["VLLM_ENGINE_EXTRA_ARGS_JSON"])
    assert args[:2] == ["--preemption-policy", "bidkv.adapters.vllm_hust.selector.BidkvPreemptionPolicy"]
    additional_index = args.index("--additional-config")
    additional = json.loads(args[additional_index + 1])
    assert "enable_utility_victim_selection" not in additional
    assert "utility_strategy" not in additional


def test_bidkv_profile_environment_reaches_engine_child_allowlist() -> None:
    result, environment = resolve("bidkv")
    assert result.returncode == 0
    assert environment["VLLM_ENGINE_EXTRA_ENV_PREFIXES"] == "BIDKV_UTILITY_"

    child_environment = {"PATH": os.environ["PATH"], **environment}
    rendered = subprocess.run(
        [sys.executable, str(CONTAINER_EXPORTS)],
        text=True,
        capture_output=True,
        check=False,
        env=child_environment,
    )
    assert rendered.returncode == 0
    exports = set(rendered.stdout.splitlines())
    assert "export BIDKV_UTILITY_ENABLE=1" in exports
    assert "export BIDKV_UTILITY_STRATEGY=bidkv" in exports
    assert "export BIDKV_UTILITY_LIVENESS_PREEMPTIONS=2" in exports
    assert "export BIDKV_UTILITY_CASCADE_GAIN_RATIO=1.25" in exports


def test_diffspec_requires_and_renders_draft_model() -> None:
    missing, _environment = resolve("diffspec")
    assert missing.returncode != 0
    assert "requires --draft-model" in missing.stderr

    result, environment = resolve("diffspec", "draft_model=/models/eagle3")
    assert result.returncode == 0
    args = json.loads(environment["VLLM_ENGINE_EXTRA_ARGS_JSON"])
    assert args[:2] == ["--tensor-parallel-size", "4"]
    assert json.loads(args[3])["model"] == "/models/eagle3"
    assert "VLLM_ENGINE_ENFORCE_EAGER" not in environment
    assert environment["VLLM_PLUGINS"] == "ascend,diffspec"
    assert environment["VLLM_ENGINE_MAX_NUM_SEQS"] == "8"


def test_latchmoe_uses_default_or_explicit_offload_budget() -> None:
    default_result, default_environment = resolve("latchmoe")
    assert default_result.returncode == 0
    assert default_environment["VLLM_ASCEND_MOE_OFFLOAD_GB"] == "14"

    result, environment = resolve("latchmoe", "offload_gb=28")
    assert result.returncode == 0
    assert environment["VLLM_ASCEND_MOE_OFFLOAD_GB"] == "28"
    assert environment["VLLM_PLUGINS"] == "ascend,moe_offload_ascend"
    assert json.loads(environment["VLLM_ENGINE_EXTRA_ARGS_JSON"])[:2] == ["--tensor-parallel-size", "4"]


def test_operator_environment_overrides_manifest_defaults() -> None:
    env = os.environ.copy()
    env["BIDKV_UTILITY_ENABLE"] = "0"
    result, environment = resolve("bidkv", env=env)

    assert result.returncode == 0
    assert environment["BIDKV_UTILITY_ENABLE"] == "0"


def test_profile_repository_ignores_stale_low_level_environment() -> None:
    env = os.environ.copy()
    env["VLLM_OPTIMIZATION_REPO_CONTAINER"] = "/workspace/stale-plugin"

    result, environment = resolve("bidkv", env=env)

    assert result.returncode == 0
    assert (
        environment["VLLM_OPTIMIZATION_REPO_CONTAINER"] == "/workspace/vllm-hust-bidkv"
    )


def test_explicit_container_repository_override_is_supported() -> None:
    result, environment = resolve(
        "bidkv",
        container_repo="/opt/vllm-hust-bidkv",
    )

    assert result.returncode == 0
    assert environment["VLLM_OPTIMIZATION_REPO_CONTAINER"] == "/opt/vllm-hust-bidkv"


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
