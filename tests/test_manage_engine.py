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

        self.assertIn("VLLM_ENGINE_CONTAINER=", template)
        self.assertIn("VLLM_ENGINE_NPU_DEVICES=0,1,2,3", template)
        self.assertIn("VLLM_ENGINE_CONDA_ENV=vllm-hust-dev", template)

    def test_readme_documents_one_command_management(self) -> None:
        readme = README.read_text()

        self.assertIn("./manage.sh start", readme)
        self.assertIn("./manage.sh restart", readme)
        self.assertIn("scripts/run_vllm_hust_engine.sh", readme)


if __name__ == "__main__":
    unittest.main()
