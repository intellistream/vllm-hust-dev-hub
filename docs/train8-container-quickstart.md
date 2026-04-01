# train8 Container Quickstart

This note is the shortest path for team members who need direct SSH access to
the official Ascend container running on `train8`.

## What This Gives You

- A persistent official Ascend container on `train8`
- An SSH port exposed from inside the container
- A normal host alias and a separate container alias
- A `quickstart.sh` menu flow that can ask for a pasted public key and wire container SSH automatically

Use the normal host alias when you want the bare machine.
Use the container alias when you want to land directly inside Docker.

## Preferred One-Time Host Setup

Run this on `train8` once:

```bash
cd /home/shuhao/vllm-hust-dev-hub
bash scripts/quickstart.sh
```

Then choose:

```text
6) 创建/启动官方 Ascend Docker instance（可交互录入 SSH 公钥）
```

That flow can now:

- reuse or create the official Ascend container
- ask you to paste an extra SSH public key and persist it under `~/.ssh/vllm-ascend-extra-authorized_keys`
- auto-enable `sshd` inside the container when host key material is available
- align the container SSH user with `/workspace` ownership so login lands in a usable workspace
- keep `/data/...`-backed workspace symlinks valid inside the container

## Scripted Alternative

Run this on `train8` once:

```bash
cd /home/shuhao/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 2222
```

What it does:

- creates or starts the official Ascend container
- installs and starts `sshd` inside the container
- copies `authorized_keys` into the container user home
- exposes the container SSH service on host port `2222`
- ensures future container restarts also bring `sshd` back automatically

## Fallback for an Existing Custom Container

If you already have a running container such as `vllm-ascend-v091-dev`, and the
preferred manager flow cannot finish because the host or container has no public
network/DNS access, use the fallback helper from the host workspace root:

```bash
cd /home/shuhao/vllm-hust-dev-hub
bash scripts/enable-existing-container-ssh.sh
```

What this fallback does:

- targets an already-running container instead of recreating it
- tries `apt-get install openssh-server` first when network access is available
- supports an offline `.deb` bundle through `OFFLINE_DEB_DIR=/path/to/debs`
- creates or aligns the container SSH user with the mounted workspace owner
- copies `authorized_keys` into the container user home
- adds `~/workspace` plus repo symlinks in `~/` so login immediately shows the code

Example with an offline package bundle:

```bash
cd /home/shuhao/vllm-hust-dev-hub
OFFLINE_DEB_DIR=/tmp/v091_ssh_debs_host \
CONTAINER_NAME=vllm-ascend-v091-dev \
bash scripts/enable-existing-container-ssh.sh
```

## Windows SSH Config

Add a second SSH alias in Windows `~/.ssh/config`.

Example:

```sshconfig
Host train8
    HostName 11.11.10.27
    User <ssh-user>
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes

Host train8-container
    HostName 127.0.0.1
    User <ssh-user>
    Port 2222
    ProxyJump train8
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    PreferredAuthentications publickey
    PubkeyAuthentication yes
    ConnectTimeout 10
    ServerAliveInterval 30
    ServerAliveCountMax 3
    HostKeyAlias train8-container
```

Keep your existing `train8` host entry unchanged for normal host access.

This `ProxyJump` form is preferred to direct public `train8:2222`, because the host's public network path may not expose port `2222` even when the container SSH service is healthy locally.

## Daily Use

Connect straight to the container with:

```bash
ssh train8-container
```

After login, the mounted workspace is available in two ways:

- directly under `~/workspace`
- as convenience symlinks such as `~/vllm-hust`, `~/vllm-hust-dev-hub`, and `~/reference-repos`

If the container was recreated and the client complains about a changed host key, clear the stale entries and retry:

```bash
ssh-keygen -R train8-container
ssh-keygen -R "[127.0.0.1]:2222"
```

Connect to the host with your existing host alias:

```bash
ssh train8
```

## Quick Check

After logging into `train8-container`, run:

```bash
python -c "import torch; import torch_npu; print(torch.npu.device_count())"
```

If everything is correct, you should see the available NPU count.

## If You Need To Change the Port

If `2222` is already used on the host, redeploy with another port:

```bash
cd /home/shuhao/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 22022
```

Then update the Windows SSH alias to match the new port.

## Notes

- The default container name is `vllm-ascend-dev`.
- The container image is managed by `ascend-runtime-manager`.
- When you do not pass `--image`, the manager asks for the Ascend hardware profile and selects the matching `v0.9.1-dev` official image variant.
- The first run is slower because the container installs `openssh-server`.
- The fallback helper defaults to `vllm-ascend-v091-dev`, because that is the common name for the manually imported `v0.9.1-dev` container.
- When the host Docker root under `/var/lib/docker` is low on space and `/data` has room, the helper can relocate Docker data-root to `/data/docker` before pulling the image.