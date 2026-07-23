from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github/workflows/quickstart-ci.yml"
QUICKSTART_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/quickstart.sh"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/ci/quickstart_ci.sh"
SMOKE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/ci/vllm_envs_smoke.py"


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

    def test_quickstart_ci_installs_smoke_deps_before_runtime_check(self) -> None:
        script_text = SCRIPT_PATH.read_text()
        main_flow = script_text[script_text.index('conda_bin="$(resolve_conda_bin)"') :]

        self.assertIn("'setuptools-scm>=8.0' setuptools-rust", script_text)
        self.assertIn("VLLM_TARGET_DEVICE=empty VLLM_USE_PRECOMPILED=0", script_text)
        self.assertLess(
            main_flow.index('if ! install_smoke_test_dependencies "$conda_bin"; then'),
            main_flow.index('"runtime check"'),
        )
        self.assertIn(
            'skip_step "runtime check" "runner flavor does not require Ascend runtime validation"',
            script_text,
        )

    def test_quickstart_installs_ascend_runtime_python_deps(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('ensure_ascend_runtime_python_packages "$repo_path"', script_text)
        self.assertIn('list_requirement_specs_from_requirements_file()', script_text)
        self.assertIn('ascend_runtime_requirement_is_optional_for_quickstart()', script_text)
        self.assertIn('mapfile -t requirement_specs < <(list_requirement_specs_from_requirements_file "$repo_path" || true)', script_text)
        self.assertIn('if ascend_runtime_requirement_is_optional_for_quickstart "$requirement_spec"; then', script_text)
        self.assertIn(
            'mapfile -t missing_requirement_specs < <(list_missing_pip_requirements_in_env "$ENV_NAME" "${required_specs[@]}" || true)',
            script_text,
        )
        self.assertIn('Installing missing or incompatible Ascend runtime Python dependencies', script_text)
        self.assertIn('run_pip_install_in_env "$ENV_NAME" -- "${missing_requirement_specs[@]}"', script_text)

    def test_quickstart_defaults_official_triton_ascend_extra_index_for_ascend(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('PIP_ASCEND_TRITON_EXTRA_INDEX_URL="https://triton-ascend.osinfra.cn/pypi/simple"', script_text)
        self.assertIn('select_pip_extra_index_url() {', script_text)
        self.assertIn('explicit_extra_index_url="$(get_first_nonempty_env PIP_EXTRA_INDEX_URL HUST_DEV_HUB_PIP_EXTRA_INDEX_URL HUST_ASCEND_MANAGER_PIP_EXTRA_INDEX_URL || true)"', script_text)
        self.assertIn('if should_reconcile_ascend_runtime; then', script_text)
        self.assertIn('printf \'%s\\n\' "$PIP_ASCEND_TRITON_EXTRA_INDEX_URL"', script_text)
        self.assertIn('PIP_SELECTED_EXTRA_INDEX_URL="$(select_pip_extra_index_url || true)"', script_text)

    def test_quickstart_validates_torch_npu_runtime_before_ascend_install(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('validate_torch_npu_runtime_in_env() {', script_text)
        self.assertIn('log_torch_npu_runtime_validation_failure_details() {', script_text)
        self.assertIn('remove_conflicting_conda_torch_packages_in_env() {', script_text)
        self.assertIn('force_reinstall_ascend_python_stack_in_env() {', script_text)
        self.assertIn('ensure_ascend_torch_runtime_healthy() {', script_text)
        self.assertIn('Removing conflicting conda torch packages from', script_text)
        self.assertIn('Force reinstalling Ascend Python stack in', script_text)
        self.assertIn('--upgrade --ignore-installed', script_text)
        self.assertIn("Detailed torch/torch-npu runtime validation traceback for", script_text)
        self.assertIn('traceback.print_exc()', script_text)
        self.assertIn('log_torch_npu_runtime_validation_failure_details "$env_name" "initial validation failure" || true', script_text)
        self.assertIn('log_torch_npu_runtime_validation_failure_details "$env_name" "post-reinstall validation failure" || true', script_text)
        self.assertIn('if ! ensure_ascend_torch_runtime_healthy "$ENV_NAME"; then', script_text)

    def test_quickstart_fails_when_ascend_repo_is_skipped_for_unhealthy_runtime(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('local fatal_failure_messages=()', script_text)
        self.assertIn('local fatal_failure_rc=0', script_text)
        self.assertIn('Aborting repository installation because a critical setup step failed.', script_text)
        self.assertIn('Conda env \'$ENV_NAME\' setup stopped because repository installation failed (rc=$install_rc)', script_text)
        self.assertIn('local install_rc=$?', script_text)
        self.assertIn('if [[ "$install_rc" -ne 0 ]]; then', script_text)
        self.assertIn('return "$fatal_failure_rc"', script_text)
        self.assertIn('return "$install_rc"', script_text)

    def test_quickstart_installs_vllm_hust_without_build_isolation(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('"$repo_path" == "$WORKSPACE_ROOT/vllm-hust"', script_text)
        self.assertIn('ensure_vllm_hust_editable_build_python_packages "$repo_path"', script_text)
        self.assertIn('ensure_vllm_hust_runtime_python_packages "$repo_path"', script_text)
        self.assertIn('pip_args=(--no-build-isolation "${pip_args[@]}")', script_text)
        self.assertIn('pip_args=(--no-deps "${pip_args[@]}")', script_text)
        self.assertIn("VLLM_TARGET_DEVICE=empty", script_text)
        self.assertIn("VLLM_USE_PRECOMPILED=0", script_text)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD=0", script_text)

    def test_quickstart_prefers_local_triton_ascend_checkout(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn("resolve_local_triton_ascend_repo()", script_text)
        self.assertIn('"${HUST_TRITON_ASCEND_REPO:-}"', script_text)
        self.assertIn('"$WORKSPACE_ROOT/triton-ascend-hust"', script_text)
        self.assertIn('--no-build-isolation -v -e "$triton_ascend_repo"', script_text)

    def test_quickstart_prepares_local_triton_build_requirements_before_editable_install(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn(
            'read_build_requirement_spec_from_pyproject "$triton_ascend_repo" "$package_spec"',
            script_text,
        )
        self.assertIn('for package_spec in cmake ninja pybind11 nanobind; do', script_text)
        self.assertIn('batch_specs+=("$package_spec")', script_text)
        self.assertLess(
            script_text.index('mapfile -t missing_batch_specs'),
            script_text.index('"installing local triton-ascend from $triton_ascend_repo"'),
        )

    def test_quickstart_fail_fast_gates_ascend_fallback(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('local rc_build_python_packages=20', script_text)
        self.assertIn('local rc_runtime_python_packages=21', script_text)
        self.assertIn('local rc_catlass_submodule=22', script_text)
        self.assertIn('local rc_editable_install=23', script_text)
        self.assertIn('local rc_plugin_validation=24', script_text)
        self.assertIn('local rc_custom_op_validation=25', script_text)
        self.assertIn('if ! ensure_ascend_build_python_packages "$repo_path" "$compile_custom_kernels"; then', script_text)
        self.assertIn('if ! ensure_ascend_runtime_python_packages "$repo_path"; then', script_text)
        self.assertIn('if ! ensure_ascend_catlass_submodule_ready "$repo_path"; then', script_text)
        self.assertIn('if ! run_with_heartbeat \\', script_text)
        self.assertIn('local ascend_install_rc=0', script_text)
        self.assertIn('install_ascend_repo_into_env "$repo_path" "$compile_custom_kernels"', script_text)
        self.assertIn('ascend_install_rc=$?', script_text)
        self.assertIn('if [[ "$ascend_install_rc" -eq 0 ]]; then', script_text)
        self.assertIn('case "$ascend_install_rc" in', script_text)
        self.assertIn('23|25)', script_text)
        self.assertIn('return "$ascend_install_rc"', script_text)

    def test_quickstart_repairs_stale_ascend_cmake_generator_cache(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('resolve_ascend_expected_cmake_generator() {', script_text)
        self.assertIn('repair_ascend_cmake_generator_cache() {', script_text)
        self.assertIn('local cache_file="$build_dir/CMakeCache.txt"', script_text)
        self.assertIn("printf 'Ninja\\n'", script_text)
        self.assertIn('Detected stale Ascend CMake generator cache', script_text)
        self.assertIn('rm -f -- "$cache_file" "$build_dir/Makefile" "$build_dir/build.ninja" "$build_dir/cmake_install.cmake"', script_text)
        self.assertIn('rm -rf -- "$cmake_files_dir"', script_text)
        self.assertIn('repair_ascend_cmake_generator_cache "$repo_path"', script_text)

    def test_quickstart_detects_cann9_installation_paths(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('/usr/local/Ascend/cann-9.0.0/compiler/version.info', script_text)
        self.assertIn('/usr/local/Ascend/cann-9.0.0/opp/version.info', script_text)
        self.assertIn('${CONDA_PREFIX:-}/Ascend/cann/compiler/version.info', script_text)
        self.assertIn('${CONDA_PREFIX:-}/Ascend/cann/opp/version.info', script_text)

    def test_quickstart_reads_setup_py_variable_backed_project_name(self) -> None:
        synthetic_setup_py = (
            'PROJECT_NAME = "my-test-project"\n'
            '\n'
            'setup(\n'
            '    name=PROJECT_NAME,\n'
            '    version="0.1.0",\n'
            ')\n'
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "setup.py").write_text(synthetic_setup_py)

            command = (
                f"source <(sed '/^main() {{/,$d' {shlex.quote(str(QUICKSTART_SCRIPT_PATH))}); "
                f"read_project_name {shlex.quote(tmpdir)}"
            )

            result = subprocess.run(
                ["bash", "-lc", command],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.stdout.strip(), "my-test-project")

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

    def test_quickstart_supports_perf_timestamps_toggle(self) -> None:
        script_text = QUICKSTART_SCRIPT_PATH.read_text()

        self.assertIn('PERF_TIMESTAMPS="${HUST_DEV_HUB_PERF_TIMESTAMPS:-0}"', script_text)
        self.assertIn('PERF_SUMMARY_LIMIT="${HUST_DEV_HUB_PERF_SUMMARY_LIMIT:-10}"', script_text)
        self.assertIn('declare -a PERF_SUMMARY_ENTRIES=()', script_text)
        self.assertIn('--perf-timestamps', script_text)
        self.assertIn('log_perf_step_start() {', script_text)
        self.assertIn('log_perf_step_end() {', script_text)
        self.assertIn('if [[ "$PERF_TIMESTAMPS" != "1" ]]; then', script_text)
        self.assertIn('log_perf_step_start "$description"', script_text)
        self.assertIn('duration=%ss | status=%s', script_text)
        self.assertIn('PERF_SUMMARY_ENTRIES+=("${duration}|${status}|${description}")', script_text)
        self.assertIn('print_perf_summary() {', script_text)
        self.assertIn("summary: top %s slowest recorded steps", script_text)
        self.assertIn('print_perf_summary_on_exit() {', script_text)
        self.assertIn('trap print_perf_summary_on_exit EXIT', script_text)
        self.assertIn('log_perf_step_end "$description" "$start_epoch" "$exit_code"', script_text)
        self.assertIn('local perf_description="clone workspace repositories"', script_text)
        self.assertIn('perf_description="create conda environment $ENV_NAME"', script_text)
        self.assertIn('perf_description="update conda environment $ENV_NAME"', script_text)
        self.assertIn('local perf_description="install workspace repositories into $ENV_NAME (mode=$install_mode, scope=$install_scope)"', script_text)
        self.assertIn('log_perf_step_end "$perf_description" "$perf_start_epoch" 0', script_text)

    def test_quickstart_perf_timestamps_cli_sets_switch(self) -> None:
        command = (
            f"source <(sed '/^main() {{/,$d' {shlex.quote(str(QUICKSTART_SCRIPT_PATH))}); "
            "parse_args --perf-timestamps; "
            'printf "%s" "$PERF_TIMESTAMPS"'
        )

        result = subprocess.run(
            ["bash", "-lc", command],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "1")


if __name__ == "__main__":
    unittest.main()
