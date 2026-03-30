from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from hust_ascend_manager.container import DEFAULT_IMAGE
from hust_ascend_manager.container import ContainerConfig
from hust_ascend_manager.container import MIN_DOCKER_PULL_FREE_SPACE_BYTES
from hust_ascend_manager.container import build_official_image
from hust_ascend_manager.container import build_container_ssh_setup_command
from hust_ascend_manager.container import build_volume_args
from hust_ascend_manager.container import container_has_expected_startup
from hust_ascend_manager.container import container_bootstrap_snippet
from hust_ascend_manager.container import container_has_expected_mounts
from hust_ascend_manager.container import container_runtime_script_path
from hust_ascend_manager.container import default_authorized_keys_source
from hust_ascend_manager.container import desired_container_cmd
from hust_ascend_manager.container import discover_device_args
from hust_ascend_manager.container import enable_container_ssh
from hust_ascend_manager.container import ensure_image_present
from hust_ascend_manager.container import install_container
from hust_ascend_manager.container import parse_ssh_enable_options
from hust_ascend_manager.container import resolve_container_image
from hust_ascend_manager.container import run_container_action


DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


def test_build_official_image_uses_expected_suffixes():
    assert build_official_image("910b", "ubuntu") == "quay.io/ascend/vllm-ascend:v0.9.1-dev"
    assert build_official_image("910b", "openeuler") == "quay.io/ascend/vllm-ascend:v0.9.1-dev-openeuler"
    assert build_official_image("a3", "ubuntu") == "quay.io/ascend/vllm-ascend:v0.9.1-dev-a3"
    assert build_official_image("a3", "openeuler") == "quay.io/ascend/vllm-ascend:v0.9.1-dev-a3-openeuler"


def test_resolve_container_image_prefers_explicit_override():
    assert resolve_container_image("quay.io/example/custom:tag", non_interactive=True) == "quay.io/example/custom:tag"


def test_resolve_container_image_noninteractive_uses_detected_variant():
    with (
        patch("hust_ascend_manager.container.detect_host_ascend_profile", return_value="a3"),
        patch("hust_ascend_manager.container.detect_host_os_flavor", return_value="openeuler"),
    ):
        image = resolve_container_image(None, non_interactive=True)

    assert image == "quay.io/ascend/vllm-ascend:v0.9.1-dev-a3-openeuler"


def test_resolve_container_image_interactively_accepts_detected_defaults():
    with (
        patch("hust_ascend_manager.container.detect_host_ascend_profile", return_value="a3"),
        patch("hust_ascend_manager.container.detect_host_os_flavor", return_value="openeuler"),
        patch("hust_ascend_manager.container._has_interactive_tty", return_value=True),
        patch("builtins.input", side_effect=["", ""]),
    ):
        image = resolve_container_image(None, non_interactive=False)

    assert image == "quay.io/ascend/vllm-ascend:v0.9.1-dev-a3-openeuler"


def test_resolve_container_image_noninteractive_falls_back_to_default_when_detection_missing():
    with (
        patch("hust_ascend_manager.container.detect_host_ascend_profile", return_value=None),
        patch("hust_ascend_manager.container.detect_host_os_flavor", return_value=None),
    ):
        image = resolve_container_image(None, non_interactive=True)

    assert image == DEFAULT_IMAGE


def test_build_volume_args_includes_workspace_and_cache(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    cache_dir = tmp_path / "cache"
    workspace_root.mkdir()
    cache_dir.mkdir()

    config = ContainerConfig(
        host_workspace_root=str(workspace_root),
        container_workspace_root="/workspace",
        host_cache_dir=str(cache_dir),
    )

    args = build_volume_args(config)

    assert f"{workspace_root}:/workspace" in args
    assert f"{cache_dir}:/root/.cache" in args


def test_build_volume_args_includes_external_symlink_targets(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    cache_dir = tmp_path / "cache"
    external_root = tmp_path / "external"
    workspace_root.mkdir()
    cache_dir.mkdir()
    external_root.mkdir()
    (workspace_root / "vllm-hust").symlink_to(external_root, target_is_directory=True)

    config = ContainerConfig(
        host_workspace_root=str(workspace_root),
        container_workspace_root="/workspace",
        host_cache_dir=str(cache_dir),
    )

    args = build_volume_args(config)

    assert f"{external_root}:{external_root}" in args


def test_container_bootstrap_snippet_sources_ascend_env():
    config = ContainerConfig(container_workdir="/workspace/vllm-hust-dev-hub")

    snippet = container_bootstrap_snippet(config)

    assert "/usr/local/Ascend/ascend-toolkit/set_env.sh" in snippet
    assert "/usr/local/Ascend/nnal/atb/set_env.sh" in snippet
    assert "cd /workspace/vllm-hust-dev-hub" in snippet


def test_default_authorized_keys_source_uses_workspace_root():
    config = ContainerConfig(container_workspace_root="/workspace")

    assert default_authorized_keys_source(config) == "/workspace/.ssh/authorized_keys"


def test_container_runtime_script_path_uses_repo_scripts_dir():
    config = ContainerConfig(container_workdir="/workspace/vllm-hust-dev-hub")

    assert container_runtime_script_path(config) == "/workspace/vllm-hust-dev-hub/scripts/ascend-container-runtime.sh"


def test_desired_container_cmd_uses_runtime_script():
    config = ContainerConfig(container_workdir="/workspace/vllm-hust-dev-hub")

    assert desired_container_cmd(config) == [
        "bash",
        "-lc",
        "bash /workspace/vllm-hust-dev-hub/scripts/ascend-container-runtime.sh",
    ]


def test_container_has_expected_startup_matches_inspected_cmd(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root), container_workdir="/workspace/vllm-hust-dev-hub")

    inspect_cmd = Mock(returncode=0, stdout='["bash", "-lc", "bash /workspace/vllm-hust-dev-hub/scripts/ascend-container-runtime.sh"]', stderr="")
    with patch("hust_ascend_manager.container.docker_capture", return_value=inspect_cmd):
        assert container_has_expected_startup(["docker"], config) is True


def test_container_has_expected_mounts_matches_volume_args(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    cache_dir = tmp_path / "cache"
    workspace_root.mkdir()
    cache_dir.mkdir()

    config = ContainerConfig(
        host_workspace_root=str(workspace_root),
        container_workspace_root="/workspace",
        host_cache_dir=str(cache_dir),
    )

    inspect_mounts = Mock(
        returncode=0,
        stdout=(
            '[{"Source": "' + str(workspace_root) + '", "Destination": "/workspace"}, '
            '{"Source": "' + str(cache_dir) + '", "Destination": "/root/.cache"}]'
        ),
        stderr="",
    )

    with (
        patch("hust_ascend_manager.container.docker_capture", return_value=inspect_mounts),
        patch(
            "hust_ascend_manager.container.build_volume_args",
            return_value=["-v", f"{workspace_root}:/workspace", "-v", f"{cache_dir}:/root/.cache"],
        ),
    ):
        assert container_has_expected_mounts(["docker"], config) is True


def test_build_container_ssh_setup_command_contains_expected_settings():
    config = ContainerConfig(container_workspace_root="/workspace")

    command = build_container_ssh_setup_command(
        config=config,
        ssh_user="shuhao",
        ssh_port=2222,
        authorized_keys_source="/workspace/.ssh/authorized_keys",
    )

    assert "apt-get install -y openssh-server" in command
    assert "Port $SSH_PORT" in command
    assert "AllowUsers $SSH_USER" in command
    assert "/workspace/.ssh/authorized_keys" in command
    assert "ln -sfn \"$WORKSPACE_ENTRY\" \"$ENTRY_LINK\"" in command
    assert "find \"$CONTAINER_WORKSPACE_ROOT\" -mindepth 1 -maxdepth 1" in command


def test_discover_device_args_includes_special_devices(tmp_path: Path):
    fake_devices = [
        tmp_path / "davinci0",
        tmp_path / "davinci1",
        tmp_path / "davinci_manager",
        tmp_path / "devmm_svm",
        tmp_path / "hisi_hdc",
    ]
    for path in fake_devices:
        path.touch()

    with patch("hust_ascend_manager.container.Path.glob", return_value=[fake_devices[0], fake_devices[1]]), patch(
        "hust_ascend_manager.container.Path.exists",
        autospec=True,
        return_value=True,
    ):
        args = discover_device_args()

    assert args == [
        "--device",
        str(fake_devices[0]),
        "--device",
        str(fake_devices[1]),
        "--device",
        "/dev/davinci_manager",
        "--device",
        "/dev/devmm_svm",
        "--device",
        "/dev/hisi_hdc",
    ]


def test_install_container_creates_container_when_missing(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    cache_dir = tmp_path / "cache"
    workspace_root.mkdir()

    config = ContainerConfig(
        image="image:latest",
        container_name="demo",
        host_workspace_root=str(workspace_root),
        container_workdir="/workspace/demo",
        host_cache_dir=str(cache_dir),
    )

    inspect_missing = Mock(returncode=1, stdout="", stderr="")
    image_present = Mock(returncode=0, stdout="", stderr="")
    run_success = Mock(returncode=0)

    with (
        patch("hust_ascend_manager.container.docker_capture", side_effect=[image_present, inspect_missing]),
        patch("hust_ascend_manager.container.discover_device_args", return_value=["--device", "/dev/davinci0"]),
        patch("hust_ascend_manager.container.run_docker", return_value=run_success) as run_mock,
    ):
        rc = install_container(["docker"], config)

    assert rc == 0
    docker_args = run_mock.call_args.args[1]
    assert docker_args[:2] == ["run", "-d"]
    assert "demo" in docker_args
    assert "image:latest" in docker_args
    assert docker_args[-3:] == ["bash", "-lc", "bash /workspace/demo/scripts/ascend-container-runtime.sh"]


def test_ensure_image_present_fails_fast_when_docker_storage_is_low(tmp_path: Path, capsys):
    docker_root = tmp_path / "docker-root"
    docker_root.mkdir()

    missing_image = Mock(returncode=1, stdout="", stderr="")
    docker_info = Mock(returncode=0, stdout=f"{docker_root}\n", stderr="")

    with (
        patch("hust_ascend_manager.container.docker_capture", side_effect=[missing_image, docker_info]),
        patch(
            "hust_ascend_manager.container.shutil.disk_usage",
            return_value=DiskUsage(total=100, used=95, free=4 * 1024 * 1024 * 1024),
        ),
        patch("hust_ascend_manager.container.run_docker") as run_mock,
    ):
        rc = ensure_image_present(["sudo", "-n", "docker"], "image:latest")

    assert rc == 1
    run_mock.assert_not_called()
    assert "Docker storage under" in capsys.readouterr().err


def test_ensure_image_present_logs_low_space_hint_after_pull_failure(tmp_path: Path, capsys):
    docker_root = tmp_path / "docker-root"
    docker_root.mkdir()

    missing_image = Mock(returncode=1, stdout="", stderr="")
    docker_info = Mock(returncode=0, stdout=f"{docker_root}\n", stderr="")
    pull_failed = Mock(returncode=1)

    with (
        patch(
            "hust_ascend_manager.container.docker_capture",
            side_effect=[missing_image, docker_info, docker_info],
        ),
        patch(
            "hust_ascend_manager.container.shutil.disk_usage",
            side_effect=[
                DiskUsage(
                    total=100,
                    used=100 - (MIN_DOCKER_PULL_FREE_SPACE_BYTES + 1),
                    free=MIN_DOCKER_PULL_FREE_SPACE_BYTES + 1,
                ),
                DiskUsage(total=100, used=95, free=4 * 1024 * 1024 * 1024),
            ],
        ),
        patch("hust_ascend_manager.container.run_docker", return_value=pull_failed),
    ):
        rc = ensure_image_present(["docker"], "image:latest")

    assert rc == 1
    assert "image pull failed and Docker storage is still low" in capsys.readouterr().out


def test_install_container_recreates_legacy_container_when_bootstrap_required(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(
        image="image:latest",
        container_name="demo",
        host_workspace_root=str(workspace_root),
        container_workdir="/workspace/demo",
    )

    with (
        patch("hust_ascend_manager.container.ensure_image_present", return_value=0),
        patch("hust_ascend_manager.container.container_exists", return_value=True),
        patch("hust_ascend_manager.container.ensure_container_image_matches", return_value=0),
        patch("hust_ascend_manager.container.container_has_expected_mounts", return_value=True),
        patch("hust_ascend_manager.container.container_has_expected_startup", return_value=False),
        patch("hust_ascend_manager.container.container_running", return_value=True),
        patch("hust_ascend_manager.container.discover_device_args", return_value=["--device", "/dev/davinci0"]),
        patch("hust_ascend_manager.container.run_docker", return_value=Mock(returncode=0)) as run_mock,
    ):
        rc = install_container(["docker"], config, require_runtime_bootstrap=True)

    assert rc == 0
    assert run_mock.call_args_list[0].args[1] == ["stop", "demo"]
    assert run_mock.call_args_list[1].args[1] == ["rm", "demo"]
    assert run_mock.call_args_list[2].args[1][0:2] == ["run", "-d"]


def test_install_container_recreates_container_when_mounts_are_stale(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(
        image="image:latest",
        container_name="demo",
        host_workspace_root=str(workspace_root),
        container_workdir="/workspace/demo",
    )

    with (
        patch("hust_ascend_manager.container.ensure_image_present", return_value=0),
        patch("hust_ascend_manager.container.container_exists", return_value=True),
        patch("hust_ascend_manager.container.ensure_container_image_matches", return_value=0),
        patch("hust_ascend_manager.container.container_has_expected_mounts", return_value=False),
        patch("hust_ascend_manager.container.container_running", return_value=True),
        patch("hust_ascend_manager.container.discover_device_args", return_value=["--device", "/dev/davinci0"]),
        patch("hust_ascend_manager.container.run_docker", return_value=Mock(returncode=0)) as run_mock,
    ):
        rc = install_container(["docker"], config)

    assert rc == 0
    assert run_mock.call_args_list[0].args[1] == ["stop", "demo"]
    assert run_mock.call_args_list[1].args[1] == ["rm", "demo"]
    assert run_mock.call_args_list[2].args[1][0:2] == ["run", "-d"]


def test_install_container_preserves_stale_container_for_shell_like_actions(tmp_path: Path, capsys):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(
        image="image:latest",
        container_name="demo",
        host_workspace_root=str(workspace_root),
        container_workdir="/workspace/demo",
    )

    with (
        patch("hust_ascend_manager.container.ensure_image_present", return_value=0),
        patch("hust_ascend_manager.container.container_exists", return_value=True),
        patch("hust_ascend_manager.container.ensure_container_image_matches", return_value=0),
        patch("hust_ascend_manager.container.container_has_expected_mounts", return_value=False),
        patch("hust_ascend_manager.container.container_running", return_value=False),
        patch("hust_ascend_manager.container.run_docker", return_value=Mock(returncode=0)) as run_mock,
    ):
        rc = install_container(["docker"], config, recreate_outdated_container=False)

    assert rc == 0
    run_mock.assert_called_once_with(["docker"], ["start", "demo"])
    assert "preserving existing container demo" in capsys.readouterr().out


def test_enable_container_ssh_runs_setup_inside_container(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.install_container", return_value=0) as install_mock,
        patch("hust_ascend_manager.container.exec_container_shell", return_value=0) as exec_mock,
    ):
        rc = enable_container_ssh(
            ["docker"],
            config,
            ssh_user="shuhao",
            ssh_port=2222,
            authorized_keys_source="/workspace/.ssh/authorized_keys",
        )

    assert rc == 0
    assert install_mock.call_args.kwargs["require_runtime_bootstrap"] is True
    assert "openssh-server" in exec_mock.call_args.args[2]


def test_parse_ssh_enable_options_uses_defaults():
    parsed = parse_ssh_enable_options([])

    assert parsed == ("shuhao", 2222, None)


def test_parse_ssh_enable_options_parses_custom_values():
    parsed = parse_ssh_enable_options(["--ssh-user", "alice", "--ssh-port", "22022", "--authorized-keys-source", "/workspace/.ssh/authorized_keys"])

    assert parsed == ("alice", 22022, "/workspace/.ssh/authorized_keys")


def test_run_container_action_ssh_enable_forwards_custom_options(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.resolve_docker_command", return_value=["docker"]),
        patch("hust_ascend_manager.container.enable_container_ssh", return_value=0) as enable_mock,
    ):
        rc = run_container_action(
            "ssh-enable",
            config,
            command=["--ssh-user", "shuhao", "--ssh-port", "22022", "--authorized-keys-source", "/workspace/.ssh/authorized_keys"],
        )

    assert rc == 0
    assert enable_mock.call_args.kwargs["ssh_user"] == "shuhao"
    assert enable_mock.call_args.kwargs["ssh_port"] == 22022
    assert enable_mock.call_args.kwargs["authorized_keys_source"] == "/workspace/.ssh/authorized_keys"


def test_run_container_action_ssh_deploy_forwards_custom_options(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.resolve_docker_command", return_value=["docker"]),
        patch("hust_ascend_manager.container.enable_container_ssh", return_value=0) as enable_mock,
    ):
        rc = run_container_action(
            "ssh-deploy",
            config,
            command=["--ssh-user", "shuhao", "--ssh-port", "22022"],
        )

    assert rc == 0
    assert enable_mock.call_args.kwargs["ssh_user"] == "shuhao"
    assert enable_mock.call_args.kwargs["ssh_port"] == 22022


def test_run_container_action_exec_forwards_command(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    config = ContainerConfig(host_workspace_root=str(workspace_root))

    with (
        patch("hust_ascend_manager.container.resolve_docker_command", return_value=["docker"]),
        patch("hust_ascend_manager.container.exec_in_container", return_value=0) as exec_mock,
    ):
        rc = run_container_action("exec", config, command=["python", "-V"])

    assert rc == 0
    assert exec_mock.call_args.args[2] == ["python", "-V"]