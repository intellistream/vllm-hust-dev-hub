from pathlib import Path
import re
import shlex
import subprocess
import unittest


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github/workflows/quickstart-ci.yml"
QUICKSTART_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/quickstart.sh"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/ci/quickstart_ci.sh"
SMOKE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/ci/vllm_envs_smoke.py"
ASCEND_REPO_PATH = Path(__file__).resolve().parents[2] / "vllm-ascend-hust"


def _extract_block(text: str, anchor: str) -> str:
    marker = f"  {anchor}:\n"
    start = text.find(marker)
    if start == -1:
        raise AssertionError(f"Missing workflow block: {anchor}")

    remainder = text[start + len(marker):]
    next_job = re.search(r"^  [A-Za-z0-9_-]+:\s*$", remainder, re.MULTILINE)
    if next_job is None:
        return remainder
    return remainder[:next_job.start()]


class QuickstartWorkflowGuardTests(unittest.TestCase):
    def test_interactive_bootstrap_keeps_bashrc_auto_activate(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('1) 一键初始化（同步仓库 + 创建/修复环境 + 安装核心仓库）', script_text)
        self.assertIn('UPDATE_BASHRC=1', script_text)

    def test_self_hosted_job_keeps_ssh_clone_guards(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text()
        self_hosted_block = _extract_block(workflow_text, "quickstart-self-hosted")

        self.assertIn(
            "ssh-key: ${{ secrets.VLLM_HUST_CI_SSH_PRIVATE_KEY }}",
            self_hosted_block,
        )
        self.assertIn(
            "- name: Prepare GitHub SSH key for downstream clones",
            self_hosted_block,
        )
        self.assertIn("GITHUB_TOKEN: ''", self_hosted_block)
        self.assertIn("CI_GITHUB_TOKEN: ''", self_hosted_block)
        self.assertIn("HUST_DEV_HUB_GIT_AUTH_MODE: ssh", self_hosted_block)

    def test_quickstart_ci_script_still_supports_ssh_mode(self) -> None:
        script_text = SCRIPT_PATH.read_text()

        self.assertIn(
            'if [[ "${HUST_DEV_HUB_GIT_AUTH_MODE:-https}" == "ssh" ]]; then',
            script_text,
        )
        self.assertIn(
            'log "Using SSH clone/auth mode for workspace repositories"',
            script_text,
        )

    def test_quickstart_ci_script_uses_torch_free_vllm_smoke(self) -> None:
        script_text = SCRIPT_PATH.read_text()
        smoke_script_text = SMOKE_SCRIPT_PATH.read_text()

        self.assertIn('run_vllm_hust_smoke_step()', script_text)
        self.assertIn('python "$HUB_ROOT/scripts/ci/vllm_envs_smoke.py" "$repo_dir"', script_text)
        self.assertNotIn('tests/test_vllm_port.py', script_text)
        self.assertIn('spec_from_file_location("vllm_envs_smoke"', smoke_script_text)
        self.assertIn('repo_dir / "vllm" / "envs.py"', smoke_script_text)

    def test_quickstart_installs_ascend_runtime_python_deps(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('ensure_ascend_runtime_python_packages "$repo_path"', script_text)
        self.assertIn('list_requirement_specs_from_requirements_file()', script_text)
        self.assertIn('ascend_runtime_requirement_is_optional_for_quickstart()', script_text)
        self.assertIn('mapfile -t requirement_specs < <(list_requirement_specs_from_requirements_file "$repo_path" || true)', script_text)
        self.assertIn('if ascend_runtime_requirement_is_optional_for_quickstart "$requirement_spec"; then', script_text)
        self.assertIn('if ! pip_requirement_satisfied_in_env "$ENV_NAME" "$requirement_spec"; then', script_text)
        self.assertIn('Installing missing or incompatible Ascend runtime Python dependencies', script_text)
        self.assertIn('run_pip_install_in_env "$ENV_NAME" -- "${missing_requirement_specs[@]}"', script_text)

    def test_quickstart_validates_torch_npu_runtime_before_ascend_install(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('validate_torch_npu_runtime_in_env() {', script_text)
        self.assertIn('remove_conflicting_conda_torch_packages_in_env() {', script_text)
        self.assertIn('force_reinstall_ascend_python_stack_in_env() {', script_text)
        self.assertIn('ensure_ascend_torch_runtime_healthy() {', script_text)
        self.assertIn('Removing conflicting conda torch packages from', script_text)
        self.assertIn('Force reinstalling Ascend Python stack in', script_text)
        self.assertIn('--upgrade --ignore-installed', script_text)
        self.assertIn('if ! ensure_ascend_torch_runtime_healthy "$ENV_NAME"; then', script_text)

    def test_quickstart_reads_setup_py_variable_backed_project_name(self) -> None:
        command = (
            f"source <(sed '/^main() {{/,$d' {shlex.quote(str(QUICKSTART_SCRIPT_PATH))}); "
            f"read_project_name {shlex.quote(str(ASCEND_REPO_PATH))}"
        )

        result = subprocess.run(
            ["bash", "-lc", command],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "vllm-ascend-hust")

    def test_quickstart_accepts_cli_override_for_ascend_lightweight_mode(self) -> None:
        command = (
            f"source <(sed '/^main() {{/,$d' {shlex.quote(str(QUICKSTART_SCRIPT_PATH))}); "
            "parse_args --ascend-lightweight; "
            "default_ascend_compile_custom_kernels"
        )

        result = subprocess.run(
            ["bash", "-lc", command],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()