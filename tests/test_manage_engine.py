from pathlib import Path
import importlib.util
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE_SCRIPT = REPO_ROOT / "manage.sh"
ENGINE_SCRIPT = REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh"
LOG_SUPERVISOR = REPO_ROOT / "scripts" / "supervise_redacted_engine.py"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
README = REPO_ROOT / "README.md"


class ManageEngineGuardTests(unittest.TestCase):
    def test_management_scripts_are_executable_and_syntax_valid(self) -> None:
        for script in (MANAGE_SCRIPT, ENGINE_SCRIPT, LOG_SUPERVISOR):
            mode = script.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{script} should be executable")
            if script.suffix == ".py":
                subprocess.run([sys.executable, "-m", "py_compile", str(script)], check=True)
            else:
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

    def test_dormant_mapping_advisory_requires_signed_context_before_docker(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "VLLM_ENGINE_CONTAINER": "dummy-container",
                "VLLM_HUST_API_KEY": "test-only-not-a-production-secret",
                "VLLM_ENGINE_DORMANT_NPU_MAPPINGS_ADVISORY": "1",
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

        self.assertEqual(result.returncode, 75)
        self.assertIn("explicit signed central authorization context", result.stderr)
        self.assertNotIn("docker", result.stderr.lower())

    def test_verified_context_makes_only_dormant_mapping_gate_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            context = fixture / "authorization-context.json"
            verifier = fixture / "verify-context.py"
            marker = fixture / "verified"
            context.write_text('{"test_fixture":true}\n')
            verifier.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "assert sys.argv[1].endswith('authorization-context.json')\n"
                "assert sys.argv[2:] == ['--expected-device', '1']\n"
                f"Path({str(marker)!r}).write_text('verified\\n')\n"
            )
            for command in ("docker", "sudo"):
                executable = fixture / command
                executable.write_text("#!/bin/sh\nexit 1\n")
                executable.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fixture}:{env['PATH']}",
                    "VLLM_ENGINE_CONTAINER": "dummy-container",
                    "VLLM_HUST_API_KEY": "test-only-not-a-production-secret",
                    "VLLM_ENGINE_DORMANT_NPU_MAPPINGS_ADVISORY": "1",
                    "VLLM_ENGINE_CENTRAL_AUTHORIZATION_CONTEXT": str(context),
                    "VLLM_ENGINE_CENTRAL_AUTHORIZATION_VERIFIER": str(verifier),
                    "VLLM_ENGINE_CENTRAL_AUTHORIZATION_PYTHON": sys.executable,
                    "VLLM_ENGINE_CENTRAL_AUTHORIZATION_DEVICE": "1",
                    "VLLM_ENGINE_CONTAINER_NPU_DEVICES": "1",
                    "VLLM_ENGINE_CONTAINER_REQUIRE_EXCLUSIVE_NPU_DEVICES": "1",
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
            self.assertTrue(marker.is_file())
            self.assertIn("dormant NPU mappings are advisory", result.stdout)
            self.assertIn("cannot access Docker socket", result.stderr)
            self.assertNotIn("exclusive NPU device mapping", result.stderr)

    def test_env_template_exposes_host_managed_docker_knobs(self) -> None:
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_ENGINE_CONTAINER=vllm-ascend-dev", template)
        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER=true", template)
        self.assertIn("VLLM_ENGINE_IMAGE=quay.io/ascend/vllm-ascend:v0.21.0rc1-openeuler", template)
        self.assertIn("VLLM_ENGINE_NPU_DEVICES=0,1,2,3", template)
        self.assertIn("VLLM_ENGINE_CONTAINER_NPU_DEVICES=1", template)
        self.assertIn("VLLM_ENGINE_CONTAINER_PRIVILEGED=0", template)
        self.assertIn("VLLM_ENGINE_PYTHON=/usr/local/python3.12.13/bin/python", template)
        self.assertIn("VLLM_ENGINE_CONDA_ENV=vllm-hust-dev", template)
        self.assertIn("VLLM_ENGINE_RESTART_POLICY=on-failure", template)
        self.assertIn("VLLM_ENGINE_DIAGNOSTIC_JOURNAL_LINES=200", template)
        self.assertIn("COMPILE_CUSTOM_KERNELS=0", template)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", template)
        self.assertIn("VLLM_PLUGINS=ascend", template)
        self.assertIn("VLLM_ENGINE_BASE_PYTHONPATH", template)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", template)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", template)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", template)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", template)

    def test_readme_documents_one_command_management(self) -> None:
        readme = README.read_text()

        self.assertIn("./manage.sh start", readme)
        self.assertIn("./manage.sh restart", readme)
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
        self.assertIn("CONTAINER_NPU_DEVICES", script)
        self.assertIn("CONTAINER_PRIVILEGED", script)
        self.assertIn("verify_central_authorization_context", script)
        self.assertIn("effective_require_exclusive_npu_devices=0", script)
        self.assertIn(
            'CONTAINER_REQUIRE_EXCLUSIVE_NPU_DEVICES="$effective_require_exclusive_npu_devices"',
            script,
        )
        self.assertIn("VLLM_ENGINE_CONTAINER_LOG_FILE", script)
        self.assertNotIn("tee -a", script)
        self.assertIn("supervise_redacted_engine.py", script)
        self.assertIn("--partial-tail-file", script)
        self.assertIn("<redacted>", LOG_SUPERVISOR.read_text())
        self.assertIn("__EXTRA_ENV_EXPORTS__", script)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", script)
        self.assertIn("torch_npu_preflight", script)
        self.assertNotIn('HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"', script)
        manage = MANAGE_SCRIPT.read_text()
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", manage)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", manage)
        self.assertIn("VLLM_OPTIMIZATION_", manage)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", manage)
        self.assertIn("VLLM_ENGINE_PYTHON", manage)
        self.assertIn('Restart=$restart_policy', manage)
        self.assertIn('diagnostics)', manage)
        self.assertIn('journalctl --user -u "$unit_name" --no-pager', manage)
        self.assertIn("redact_diagnostics", manage)
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

    def test_engine_launcher_has_generic_optimization_repo_overlay(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("optimization_repo_container", script)
        self.assertIn("optimization_src_subdir", script)
        self.assertIn("engine_base_pythonpath", script)
        self.assertIn('plugins="${plugins},${optimization_plugin}"', script)

    def test_log_supervisor_redacts_and_seals_partial_tail(self) -> None:
        spec = importlib.util.spec_from_file_location("log_supervisor", LOG_SUPERVISOR)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "engine.log"
            tail = root / "partial-tail.log"
            output = io.BytesIO()
            code = (
                "import sys; "
                "sys.stdout.write('Bearer fixture-secret\\n'); "
                "sys.stdout.write('partial TOKEN=value'); "
                "sys.stdout.flush(); raise SystemExit(3)"
            )
            status = module.supervise(
                [sys.executable, "-c", code],
                log_path=log.resolve(),
                partial_tail_path=tail.resolve(),
                output=output,
            )
            self.assertEqual(status, 3)
            self.assertNotIn(b"fixture-secret", log.read_bytes())
            self.assertNotIn(b"TOKEN=value", log.read_bytes())
            self.assertEqual(tail.read_bytes(), b"partial TOKEN=<redacted>")

    def test_log_supervisor_consumer_exit_fails_closed_without_restart(self) -> None:
        spec = importlib.util.spec_from_file_location("log_supervisor", LOG_SUPERVISOR)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class FailedConsumer(io.BytesIO):
            def write(self, value: bytes) -> int:
                raise BrokenPipeError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status = module.supervise(
                [
                    sys.executable,
                    "-c",
                    "import time; print('one child', flush=True); time.sleep(30)",
                ],
                log_path=(root / "engine.log").resolve(),
                partial_tail_path=(root / "partial-tail.log").resolve(),
                output=FailedConsumer(),
            )
            self.assertEqual(status, 75)
            self.assertEqual((root / "engine.log").read_text(), "one child\n")


if __name__ == "__main__":
    unittest.main()
