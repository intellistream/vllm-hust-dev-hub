from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IMAGE = "quay.io/ascend/vllm-ascend:v0.13.0-a3"
DEFAULT_CONTAINER_NAME = "vllm-ascend-dev"
DEFAULT_CONTAINER_WORKSPACE_ROOT = "/workspace"
DEFAULT_SHM_SIZE = "16g"
DEFAULT_CACHE_SUBDIR = ".cache"
DEFAULT_CONTAINER_SSH_PORT = 2222
DEFAULT_CONTAINER_SSH_USER = "shuhao"
STATUS_TABLE_FORMAT = "table {{.Names}}\t{{.Status}}\t{{.Image}}"
IDLE_COMMAND = "trap : TERM INT; sleep infinity & wait"
MIN_DOCKER_PULL_FREE_SPACE_BYTES = 8 * 1024 * 1024 * 1024


@dataclass(slots=True)
class ContainerConfig:
    image: str = DEFAULT_IMAGE
    container_name: str = DEFAULT_CONTAINER_NAME
    host_workspace_root: str = ""
    container_workspace_root: str = DEFAULT_CONTAINER_WORKSPACE_ROOT
    container_workdir: str = ""
    host_cache_dir: str = ""
    shm_size: str = DEFAULT_SHM_SIZE

    def __post_init__(self) -> None:
        if not self.host_workspace_root:
            self.host_workspace_root = _default_host_workspace_root()
        if not self.container_workdir:
            self.container_workdir = f"{self.container_workspace_root.rstrip('/')}/vllm-hust-dev-hub"
        if not self.host_cache_dir:
            self.host_cache_dir = str(Path.home() / DEFAULT_CACHE_SUBDIR)


def _default_host_workspace_root() -> str:
    return str(Path.cwd())


def _log(message: str) -> None:
    print(f"[container] {message}")


def _fail(message: str) -> int:
    print(f"[container] {message}", file=sys.stderr)
    return 1


def _format_bytes(num_bytes: int) -> str:
    gib = 1024 * 1024 * 1024
    if num_bytes >= gib:
        return f"{num_bytes / gib:.1f} GiB"

    mib = 1024 * 1024
    return f"{num_bytes / mib:.1f} MiB"


def _can_run_command(cmd: list[str]) -> bool:
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def resolve_docker_command() -> list[str] | None:
    docker = shutil.which("docker")
    if docker and _can_run_command([docker, "info"]):
        return [docker]

    sudo = shutil.which("sudo")
    if docker and sudo and _can_run_command([sudo, "-n", docker, "info"]):
        return [sudo, "-n", docker]

    return None


def run_docker(docker_cmd: list[str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(docker_cmd + args, text=True)


def docker_capture(
    docker_cmd: list[str],
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        docker_cmd + args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def docker_root_dir(docker_cmd: list[str]) -> Path | None:
    proc = docker_capture(docker_cmd, ["info", "--format", "{{.DockerRootDir}}"])
    if proc.returncode != 0:
        return None

    docker_root = proc.stdout.strip()
    if not docker_root:
        return None

    return Path(docker_root)


def low_docker_storage_message(docker_cmd: list[str], image: str) -> str | None:
    root_dir = docker_root_dir(docker_cmd)
    if root_dir is None:
        return None

    try:
        free_bytes = shutil.disk_usage(root_dir).free
    except OSError:
        return None

    if free_bytes >= MIN_DOCKER_PULL_FREE_SPACE_BYTES:
        return None

    usage_cmd = shlex.join(docker_cmd + ["system", "df"])
    return (
        f"Docker storage under {root_dir} only has {_format_bytes(free_bytes)} free, "
        f"below the conservative {_format_bytes(MIN_DOCKER_PULL_FREE_SPACE_BYTES)} needed "
        f"to pull and extract large images like {image}. Free space first, then retry. "
        f"Inspect current usage with: {usage_cmd}"
    )


def container_exists(docker_cmd: list[str], name: str) -> bool:
    return docker_capture(docker_cmd, ["container", "inspect", name]).returncode == 0


def container_running(docker_cmd: list[str], name: str) -> bool:
    proc = docker_capture(docker_cmd, ["inspect", "-f", "{{.State.Running}}", name])
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def ensure_image_present(docker_cmd: list[str], image: str) -> int:
    if docker_capture(docker_cmd, ["image", "inspect", image]).returncode == 0:
        return 0

    storage_message = low_docker_storage_message(docker_cmd, image)
    if storage_message is not None:
        return _fail(storage_message)

    _log(f"pulling image {image}")
    rc = run_docker(docker_cmd, ["pull", image]).returncode
    if rc != 0:
        storage_message = low_docker_storage_message(docker_cmd, image)
        if storage_message is not None:
            _log(f"image pull failed and Docker storage is still low. {storage_message}")
    return rc


def ensure_host_paths(config: ContainerConfig) -> int:
    if not Path(config.host_workspace_root).is_dir():
        return _fail(f"host workspace root not found: {config.host_workspace_root}")

    Path(config.host_cache_dir).mkdir(parents=True, exist_ok=True)
    return 0


def discover_device_args() -> list[str]:
    device_args: list[str] = []
    device_paths = sorted(Path("/dev").glob("davinci[0-9]*"))
    for device_path in device_paths:
        device_args.extend(["--device", str(device_path)])

    for extra_path in (
        Path("/dev/davinci_manager"),
        Path("/dev/devmm_svm"),
        Path("/dev/hisi_hdc"),
    ):
        if extra_path.exists():
            device_args.extend(["--device", str(extra_path)])

    return device_args


def build_volume_args(config: ContainerConfig) -> list[str]:
    volume_args = [
        "-v",
        f"{config.host_workspace_root}:{config.container_workspace_root}",
        "-v",
        f"{config.host_cache_dir}:/root/.cache",
    ]

    symlink_mounts: set[tuple[str, str]] = set()
    workspace_root = Path(config.host_workspace_root)
    if workspace_root.is_dir():
        for child_path in workspace_root.iterdir():
            if not child_path.is_symlink():
                continue

            try:
                resolved_path = child_path.resolve(strict=True)
            except OSError:
                continue

            resolved_str = str(resolved_path)
            if resolved_str.startswith(f"{config.host_workspace_root.rstrip('/')}/"):
                continue

            symlink_mounts.add((resolved_str, resolved_str))

    for source_path, target_path in sorted(symlink_mounts):
        volume_args.extend(["-v", f"{source_path}:{target_path}"])

    for host_path in (
        "/usr/local/dcmi",
        "/usr/local/Ascend/driver/tools/hccn_tool",
        "/usr/local/sbin/npu-smi",
        "/usr/local/Ascend/driver/lib64",
        "/usr/local/Ascend/driver/version.info",
        "/etc/ascend_install.info",
    ):
        if Path(host_path).exists():
            volume_args.extend(["-v", f"{host_path}:{host_path}"])

    return volume_args


def ensure_container_image_matches(docker_cmd: list[str], config: ContainerConfig) -> int:
    proc = docker_capture(docker_cmd, ["inspect", "-f", "{{.Config.Image}}", config.container_name])
    current_image = proc.stdout.strip() if proc.returncode == 0 else ""
    if current_image and current_image != config.image:
        return _fail(
            f"container {config.container_name} already exists with image {current_image}. "
            "Remove it first or choose a different --container-name."
        )
    return 0


def container_has_expected_mounts(docker_cmd: list[str], config: ContainerConfig) -> bool:
    proc = docker_capture(docker_cmd, ["inspect", "-f", "{{json .Mounts}}", config.container_name])
    if proc.returncode != 0:
        return False

    try:
        mounts = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False

    actual_mounts = {
        (mount.get("Source", ""), mount.get("Destination", ""))
        for mount in mounts
    }

    expected_mounts = set()
    volume_args = build_volume_args(config)
    for index in range(0, len(volume_args), 2):
        if volume_args[index] != "-v":
            continue
        source_path, target_path = volume_args[index + 1].split(":", 1)
        expected_mounts.add((source_path, target_path))

    return expected_mounts.issubset(actual_mounts)


def container_bootstrap_snippet(config: ContainerConfig) -> str:
    lines = [
        "if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then",
        "  source /usr/local/Ascend/ascend-toolkit/set_env.sh",
        "fi",
        "if [[ -f /usr/local/Ascend/nnal/atb/set_env.sh ]]; then",
        "  source /usr/local/Ascend/nnal/atb/set_env.sh",
        "fi",
        f"cd {shlex.quote(config.container_workdir)}",
    ]
    return "\n".join(lines)


def default_authorized_keys_source(config: ContainerConfig) -> str:
    return f"{config.container_workspace_root.rstrip('/')}/.ssh/authorized_keys"


def container_runtime_script_path(config: ContainerConfig) -> str:
    return f"{config.container_workdir.rstrip('/')}/scripts/ascend-container-runtime.sh"


def desired_container_cmd(config: ContainerConfig) -> list[str]:
    return ["bash", "-lc", f"bash {shlex.quote(container_runtime_script_path(config))}"]


def container_has_expected_startup(docker_cmd: list[str], config: ContainerConfig) -> bool:
    proc = docker_capture(docker_cmd, ["inspect", "-f", "{{json .Config.Cmd}}", config.container_name])
    if proc.returncode != 0:
        return False
    try:
        current_cmd = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False
    return current_cmd == desired_container_cmd(config)


def exec_container_shell(docker_cmd: list[str], config: ContainerConfig, shell_command: str) -> int:
    return run_docker(
        docker_cmd,
        ["exec", config.container_name, "bash", "-lc", shell_command],
    ).returncode


def build_container_ssh_setup_command(
    config: ContainerConfig,
    ssh_user: str,
    ssh_port: int,
    authorized_keys_source: str,
) -> str:
    user_home = f"/home/{ssh_user}"
    return "\n".join(
        [
            "set -euo pipefail",
            f"AUTHORIZED_KEYS_SOURCE={shlex.quote(authorized_keys_source)}",
            f"CONTAINER_WORKSPACE_ROOT={shlex.quote(config.container_workspace_root)}",
            f"SSH_USER={shlex.quote(ssh_user)}",
            f"SSH_PORT={shlex.quote(str(ssh_port))}",
            "if [[ ! -f \"$AUTHORIZED_KEYS_SOURCE\" ]]; then",
            "  echo \"[container] authorized_keys source not found: $AUTHORIZED_KEYS_SOURCE\" >&2",
            "  exit 1",
            "fi",
            "export DEBIAN_FRONTEND=noninteractive",
            "if ! command -v sshd >/dev/null 2>&1; then",
            "  apt-get update",
            "  apt-get install -y openssh-server",
            "fi",
            "WORKSPACE_UID=$(stat -c %u \"$CONTAINER_WORKSPACE_ROOT\" 2>/dev/null || echo 0)",
            "WORKSPACE_GID=$(stat -c %g \"$CONTAINER_WORKSPACE_ROOT\" 2>/dev/null || echo 0)",
            "SSH_GROUP=$SSH_USER",
            "if [[ \"$WORKSPACE_GID\" != \"0\" ]]; then",
            "  if getent group \"$WORKSPACE_GID\" >/dev/null 2>&1; then",
            "    SSH_GROUP=$(getent group \"$WORKSPACE_GID\" | cut -d: -f1)",
            "  elif getent group \"$SSH_USER\" >/dev/null 2>&1; then",
            "    groupmod -g \"$WORKSPACE_GID\" \"$SSH_USER\"",
            "    SSH_GROUP=$SSH_USER",
            "  else",
            "    groupadd -g \"$WORKSPACE_GID\" \"$SSH_USER\"",
            "  fi",
            "fi",
            "if ! id -u \"$SSH_USER\" >/dev/null 2>&1; then",
            "  if [[ \"$WORKSPACE_UID\" != \"0\" && \"$WORKSPACE_GID\" != \"0\" ]]; then",
            "    useradd -m -u \"$WORKSPACE_UID\" -g \"$SSH_GROUP\" -s /bin/bash \"$SSH_USER\"",
            "  else",
            "    useradd -m -s /bin/bash \"$SSH_USER\"",
            "  fi",
            "else",
            "  CURRENT_UID=$(id -u \"$SSH_USER\")",
            "  CURRENT_GID=$(id -g \"$SSH_USER\")",
            "  if [[ \"$WORKSPACE_UID\" != \"0\" && \"$CURRENT_UID\" != \"$WORKSPACE_UID\" ]]; then",
            "    usermod -u \"$WORKSPACE_UID\" \"$SSH_USER\"",
            "  fi",
            "  if [[ \"$WORKSPACE_GID\" != \"0\" && \"$CURRENT_GID\" != \"$WORKSPACE_GID\" ]]; then",
            "    usermod -g \"$SSH_GROUP\" \"$SSH_USER\"",
            "  fi",
            "fi",
            f"chown -R \"$SSH_USER\":\"$SSH_GROUP\" {shlex.quote(user_home)}",
            f"install -d -m 700 -o \"$SSH_USER\" -g \"$SSH_USER\" {shlex.quote(user_home)}/.ssh",
            f"cp \"$AUTHORIZED_KEYS_SOURCE\" {shlex.quote(user_home)}/.ssh/authorized_keys",
            f"chown \"$SSH_USER\":\"$SSH_GROUP\" {shlex.quote(user_home)}/.ssh/authorized_keys",
            f"chmod 600 {shlex.quote(user_home)}/.ssh/authorized_keys",
            "mkdir -p /run/sshd",
            "ssh-keygen -A",
            "cat > /etc/ssh/sshd_config.d/vllm-ascend.conf <<EOF",
            "Port $SSH_PORT",
            "PubkeyAuthentication yes",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "ChallengeResponseAuthentication no",
            "PermitRootLogin no",
            "UsePAM yes",
            "X11Forwarding no",
            "AllowUsers $SSH_USER",
            "AuthorizedKeysFile .ssh/authorized_keys",
            "EOF",
            "pkill sshd || true",
            "/usr/sbin/sshd -f /etc/ssh/sshd_config",
            "echo \"[container] sshd is ready on host port $SSH_PORT for user $SSH_USER\"",
        ]
    )


def install_container(
    docker_cmd: list[str],
    config: ContainerConfig,
    require_runtime_bootstrap: bool = False,
) -> int:
    rc = ensure_host_paths(config)
    if rc != 0:
        return rc

    rc = ensure_image_present(docker_cmd, config.image)
    if rc != 0:
        return rc

    if container_exists(docker_cmd, config.container_name):
        rc = ensure_container_image_matches(docker_cmd, config)
        if rc != 0:
            return rc

        if (require_runtime_bootstrap and not container_has_expected_startup(docker_cmd, config)) or not container_has_expected_mounts(docker_cmd, config):
            _log(
                f"recreating container {config.container_name} so startup hooks and bind mounts match the current quickstart configuration"
            )
            if container_running(docker_cmd, config.container_name):
                rc = run_docker(docker_cmd, ["stop", config.container_name]).returncode
                if rc != 0:
                    return rc
            rc = run_docker(docker_cmd, ["rm", config.container_name]).returncode
            if rc != 0:
                return rc
        else:
            if container_running(docker_cmd, config.container_name):
                _log(f"container {config.container_name} is already running")
                return 0

            _log(f"starting existing container {config.container_name}")
            return run_docker(docker_cmd, ["start", config.container_name]).returncode

    device_args = discover_device_args()
    if not device_args:
        return _fail("no Ascend device nodes were found under /dev")

    volume_args = build_volume_args(config)
    _log(f"creating container {config.container_name} from {config.image}")
    run_args = [
        "run",
        "-d",
        "--privileged",
        "--name",
        config.container_name,
        "--shm-size",
        config.shm_size,
        "--net=host",
        "-w",
        config.container_workdir,
        *device_args,
        *volume_args,
        config.image,
        *desired_container_cmd(config),
    ]
    return run_docker(docker_cmd, run_args).returncode


def open_shell(docker_cmd: list[str], config: ContainerConfig) -> int:
    rc = install_container(docker_cmd, config)
    if rc != 0:
        return rc

    bootstrap = container_bootstrap_snippet(config)
    return run_docker(
        docker_cmd,
        ["exec", "-it", config.container_name, "bash", "-lc", f"{bootstrap}; exec bash -i"],
    ).returncode


def exec_in_container(docker_cmd: list[str], config: ContainerConfig, command: list[str]) -> int:
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        return _fail("container exec requires a command after '--'")

    rc = install_container(docker_cmd, config)
    if rc != 0:
        return rc

    bootstrap = container_bootstrap_snippet(config)
    shell_command = f"{bootstrap}; {shlex.join(command)}"
    return exec_container_shell(docker_cmd, config, shell_command)


def enable_container_ssh(
    docker_cmd: list[str],
    config: ContainerConfig,
    ssh_user: str,
    ssh_port: int,
    authorized_keys_source: str | None,
) -> int:
    rc = install_container(docker_cmd, config, require_runtime_bootstrap=True)
    if rc != 0:
        return rc

    auth_keys = authorized_keys_source or default_authorized_keys_source(config)
    setup_command = build_container_ssh_setup_command(
        config=config,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        authorized_keys_source=auth_keys,
    )
    return exec_container_shell(docker_cmd, config, setup_command)


def parse_ssh_enable_options(command: list[str]) -> tuple[str, int, str | None] | None:
    container_command = list(command)
    ssh_user = DEFAULT_CONTAINER_SSH_USER
    ssh_port = DEFAULT_CONTAINER_SSH_PORT
    authorized_keys_source = None

    while container_command:
        current = container_command.pop(0)
        if current == "--ssh-user":
            if not container_command:
                _fail("--ssh-user requires a value")
                return None
            ssh_user = container_command.pop(0)
            continue
        if current == "--ssh-port":
            if not container_command:
                _fail("--ssh-port requires a value")
                return None
            try:
                ssh_port = int(container_command.pop(0))
            except ValueError:
                _fail("--ssh-port must be an integer")
                return None
            continue
        if current == "--authorized-keys-source":
            if not container_command:
                _fail("--authorized-keys-source requires a value")
                return None
            authorized_keys_source = container_command.pop(0)
            continue
        _fail(f"unknown ssh option: {current}")
        return None

    return ssh_user, ssh_port, authorized_keys_source


def show_status(docker_cmd: list[str], config: ContainerConfig) -> int:
    if not container_exists(docker_cmd, config.container_name):
        _log(f"container {config.container_name} does not exist")
        return 0

    return run_docker(
        docker_cmd,
        [
            "ps",
            "-a",
            "--filter",
            f"name=^{config.container_name}$",
            "--format",
            STATUS_TABLE_FORMAT,
        ],
    ).returncode


def stop_container(docker_cmd: list[str], config: ContainerConfig) -> int:
    if not container_exists(docker_cmd, config.container_name):
        _log(f"container {config.container_name} does not exist")
        return 0

    if not container_running(docker_cmd, config.container_name):
        _log(f"container {config.container_name} is already stopped")
        return 0

    rc = run_docker(docker_cmd, ["stop", config.container_name]).returncode
    if rc == 0:
        _log(f"stopped {config.container_name}")
    return rc


def remove_container(docker_cmd: list[str], config: ContainerConfig) -> int:
    if not container_exists(docker_cmd, config.container_name):
        _log(f"container {config.container_name} does not exist")
        return 0

    if container_running(docker_cmd, config.container_name):
        rc = run_docker(docker_cmd, ["stop", config.container_name]).returncode
        if rc != 0:
            return rc

    rc = run_docker(docker_cmd, ["rm", config.container_name]).returncode
    if rc == 0:
        _log(f"removed {config.container_name}")
    return rc


def pull_image(docker_cmd: list[str], config: ContainerConfig) -> int:
    return ensure_image_present(docker_cmd, config.image)


def run_container_action(action: str, config: ContainerConfig, command: list[str] | None = None) -> int:
    docker_cmd = resolve_docker_command()
    if docker_cmd is None:
        return _fail(
            "docker is unavailable. Make sure the daemon is running and either direct docker access or 'sudo -n docker' works."
        )

    if action in {"install", "start"}:
        return install_container(docker_cmd, config)
    if action == "shell":
        return open_shell(docker_cmd, config)
    if action == "exec":
        return exec_in_container(docker_cmd, config, list(command or []))
    if action in {"ssh-enable", "ssh-deploy"}:
        parsed = parse_ssh_enable_options(list(command or []))
        if parsed is None:
            return 1
        ssh_user, ssh_port, authorized_keys_source = parsed
        return enable_container_ssh(
            docker_cmd,
            config,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            authorized_keys_source=authorized_keys_source,
        )
    if action == "status":
        return show_status(docker_cmd, config)
    if action == "stop":
        return stop_container(docker_cmd, config)
    if action == "rm":
        return remove_container(docker_cmd, config)
    if action == "pull":
        return pull_image(docker_cmd, config)

    return _fail(f"unknown container action: {action}")