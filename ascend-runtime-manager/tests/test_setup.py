from __future__ import annotations

import os
from unittest.mock import Mock
from unittest.mock import patch

from hust_ascend_manager import setup


def test_setup_environment_continues_when_runtime_report_is_incomplete(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"python_stack": {"torch": "2.9.0", "torch_npu": "2.9.0"}}',
        encoding="utf-8",
    )

    report = {
        "python_stack": {
            "torch": None,
            "torch_npu": None,
        }
    }

    with (
        patch("hust_ascend_manager.setup.collect_report", return_value=report),
        patch("hust_ascend_manager.setup._pip_install", return_value=0) as pip_install,
    ):
        rc = setup.setup_environment(
            manifest_path=str(manifest),
            apply_system=False,
            install_python_stack=True,
            dry_run=False,
        )

    assert rc == 0
    pip_install.assert_called_once_with(["torch==2.9.0", "torch-npu==2.9.0"])


def test_run_shell_fails_fast_when_group_membership_is_missing_in_noninteractive_mode():
    with patch("hust_ascend_manager.setup._user_in_group", return_value=False):
        rc = setup._run_shell(
            "echo test",
            requires_group="HwHiAiUser",
            non_interactive=True,
        )

    assert rc == setup.GROUP_MEMBERSHIP_REQUIRED_EXIT_CODE


def test_run_shell_uses_sudo_n_in_noninteractive_mode():
    fake_proc = Mock(returncode=0)

    with patch("hust_ascend_manager.setup.subprocess.run", return_value=fake_proc) as run_mock:
        rc = setup._run_shell("echo test", use_sudo=True, non_interactive=True)

    assert rc == 0
    assert run_mock.call_args.args[0] == ["bash", "-c", "sudo -n echo test"]


def test_build_pip_install_cmd_adds_retry_timeout_and_resume_flags():
    with patch("hust_ascend_manager.setup._pip_supports_option", return_value=True):
        cmd = setup._build_pip_install_cmd(["torch==2.9.0"])

    assert cmd == [
        "python",
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--retries",
        str(setup.DEFAULT_PIP_RETRIES),
        "--timeout",
        str(setup.DEFAULT_PIP_TIMEOUT_SECONDS),
        "--resume-retries",
        str(setup.DEFAULT_PIP_RESUME_RETRIES),
        "torch==2.9.0",
    ]


def test_pip_install_uses_auto_selected_mirror_and_disable_version_check():
    fake_proc = Mock(returncode=0)

    with (
        patch("hust_ascend_manager.setup._build_pip_install_cmd", return_value=["python", "-m", "pip", "install", "torch==2.9.0"]),
        patch("hust_ascend_manager.setup._select_pip_index_url", return_value="https://pypi.tuna.tsinghua.edu.cn/simple"),
        patch("hust_ascend_manager.setup.subprocess.run", return_value=fake_proc) as run_mock,
        patch.dict(os.environ, {}, clear=True),
    ):
        rc = setup._pip_install(["torch==2.9.0"])

    assert rc == 0
    env = run_mock.call_args.kwargs["env"]
    assert env["PIP_INDEX_URL"] == "https://pypi.tuna.tsinghua.edu.cn/simple"
    assert env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"


def test_select_pip_index_url_respects_disable_flag():
    with patch.dict(os.environ, {"HUST_ASCEND_MANAGER_DISABLE_PYPI_MIRROR_AUTOSET": "1"}, clear=True):
        assert setup._select_pip_index_url() is None
