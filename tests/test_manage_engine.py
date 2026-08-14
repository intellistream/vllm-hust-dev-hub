from pathlib import Path
import os
import stat
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE_SCRIPT = REPO_ROOT / "manage.sh"
ENGINE_SCRIPT = REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
README = REPO_ROOT / "README.md"
SMOKE_PROFILE = REPO_ROOT / "profiles" / "smoke-qwen2.5-7b-npu1.env"


class ManageEngineGuardTests(unittest.TestCase):
    def test_management_scripts_are_executable_and_syntax_valid(self) -> None:
        for script in (MANAGE_SCRIPT, ENGINE_SCRIPT):
            mode = script.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{script} should be executable")
            subprocess.run(["bash", "-n", str(script)], check=True)

    def test_empty_api_key_fails_before_docker_access(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "VLLM_ENGINE_CONTAINER": "dummy-container",
                "VLLM_HUST_API_KEY": "EMPTY",
            }
        )
        result = subprocess.run(
            [str(ENGINE_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("real API key", result.stderr)
        self.assertNotIn("Docker container", result.stderr)

    def test_env_template_exposes_host_managed_docker_knobs(self) -> None:
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_ENGINE_CONTAINER=vllm-ascend-dev", template)
        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER=true", template)
        self.assertIn("VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env", template)
        self.assertIn("VLLM_ENGINE_IMAGE=quay.io/ascend/vllm-ascend:v0.21.0rc1-openeuler", template)
        self.assertIn("VLLM_ENGINE_NPU_DEVICES=0,1,2,3", template)
        self.assertIn("VLLM_ENGINE_PYTHON=/usr/local/python3.12.13/bin/python", template)
        self.assertIn("VLLM_ENGINE_CONDA_ENV=vllm-hust-dev", template)
        self.assertIn("COMPILE_CUSTOM_KERNELS=0", template)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", template)
        self.assertIn("VLLM_PLUGINS=ascend,ascend_kv_connector,ascend_model", template)
        self.assertIn("VLLM_ENGINE_BASE_PYTHONPATH", template)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", template)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", template)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", template)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", template)
        self.assertIn("VLLM_ENGINE_CONTAINER_HOME", template)
        self.assertIn("VLLM_ENGINE_KV_CACHE_DTYPE", template)
        self.assertIn("VLLM_ENGINE_KV_CACHE_MEMORY_BYTES", template)

    def test_readme_documents_one_command_management(self) -> None:
        readme = README.read_text()

        self.assertIn("./manage.sh start", readme)
        self.assertIn("./manage.sh restart", readme)
        self.assertIn("VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env", readme)
        self.assertIn("scripts/run_vllm_hust_engine.sh", readme)
        self.assertIn("pulls/creates it automatically", readme)

    def test_engine_launcher_bootstraps_missing_container(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER", script)
        self.assertIn("scripts/ascend-official-container.sh", script)
        self.assertIn("VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE", script)
        self.assertIn("EnvironmentFile=-", MANAGE_SCRIPT.read_text())
        self.assertIn("write_unit_environment", MANAGE_SCRIPT.read_text())
        self.assertIn('"KEY"', MANAGE_SCRIPT.read_text())
        self.assertIn("v0.21.0rc1-openeuler", script)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", script)
        self.assertIn("--kv-cache-dtype", script)
        self.assertIn("--kv-cache-memory-bytes", script)
        self.assertIn("VLLM_ENGINE_CONTAINER_LOG_FILE", script)
        self.assertIn("ascend_model_loader", script)
        self.assertIn("tee -a", script)
        self.assertIn("<redacted>", script)
        self.assertIn("__EXTRA_ENV_EXPORTS__", script)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", script)
        self.assertIn("torch_npu_preflight", script)
        self.assertNotIn('HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"', script)
        manage = MANAGE_SCRIPT.read_text()
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", manage)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", manage)
        self.assertIn('"VLLM_ASCEND_ENABLE_MLAPO"', script)
        self.assertIn('"VLLM_ASCEND_KV_CACHE_FREE_MEMORY_FRACTION"', script)
        self.assertIn('"VLLM_ENGINE_CONTAINER_HOME"', script)
        self.assertIn("VLLM_ENGINE_ENV_FILE", manage)
        self.assertIn("VLLM_OPTIMIZATION_", manage)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", manage)
        self.assertIn("VLLM_ENGINE_PYTHON", manage)
        self.assertLess(
            manage.index('load_dotenv "$repo_root/.env"'),
            manage.index('unit_name="${VLLM_ENGINE_SYSTEMD_UNIT'),
        )

    def test_container_runtime_can_keep_alive_without_ssh_env(self) -> None:
        runtime = (REPO_ROOT / "scripts" / "ascend-container-runtime.sh").read_text()

        self.assertIn("CONTAINER_SSH_USER:=shuhao", runtime)
        self.assertNotIn("CONTAINER_SSH_USER:?Error", runtime)

    def test_engine_launcher_stays_repo_agnostic(self) -> None:
        script = ENGINE_SCRIPT.read_text()
        manage = MANAGE_SCRIPT.read_text()
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_PLUGINS", script)
        self.assertIn("ENGINE_PYTHON", script)
        self.assertIn('"$ENGINE_PYTHON"', script)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", script)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", script)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", script)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", script)
        for text in (script, manage, template):
            self.assertNotIn("segment_reuse", text)
            self.assertNotIn("SEGMENT_REUSE", text)

    def test_engine_launcher_has_no_hard_coded_model_default(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_MODEL_PATH or MODEL_ID must be set", script)
        self.assertNotIn(
            "model_path=\"${VLLM_ENGINE_MODEL_PATH:-${MODEL_ID:-/data/shared_models",
            script,
        )

    def test_smoke_profile_is_non_secret_and_single_npu(self) -> None:
        profile = SMOKE_PROFILE.read_text()

        self.assertIn("VLLM_ENGINE_NPU_DEVICES=1", profile)
        self.assertIn(
            "VLLM_ENGINE_MODEL_PATH=/data/shared_models/Qwen2.5-7B-Instruct",
            profile,
        )
        self.assertIn("VLLM_PLUGINS=ascend", profile)
        self.assertNotIn("VLLM_HUST_API_KEY", profile)
        self.assertNotIn("TOKEN=", profile)
        self.assertNotIn("SECRET=", profile)

    def test_engine_launcher_has_generic_optimization_repo_overlay(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("optimization_repo_container", script)
        self.assertIn("optimization_src_subdir", script)
        self.assertIn("engine_base_pythonpath", script)
        self.assertIn('plugins="${plugins},${optimization_plugin}"', script)


if __name__ == "__main__":
    unittest.main()
