# vLLM-HUST 团队开发环境全流程说明

本文档用于发给团队成员，统一说明从 Docker instance 到源码环境的完整搭建流程。

适用场景：

- 需要在 Ascend 官方容器里开发或调试 `vllm-hust`
- 需要通过 SSH 直接连到容器里的开发环境
- 需要一键拉齐 `vllm-hust-dev-hub` 相关仓库并创建 `conda` 开发环境

## 结论先说

推荐主流程如下：

1. 在目标机器上准备或创建官方 Ascend Docker instance。
2. 如果需要从本地直接连进容器，优先使用 `quickstart.sh` 的菜单 6 完成容器启动和 SSH 自动配置，再在本地配置 `~/.ssh/config`。
3. 在容器内或目标开发机上克隆 `vllm-hust-dev-hub`。
4. 执行 `bash scripts/quickstart.sh`，选择 `Recommended bootstrap (sync repos + conda env)`。
5. 需要时执行 `conda activate vllm-hust-dev` 进入环境。
6. 只有在补装、重装或刷新源码安装时，才需要再次运行 `quickstart.sh` 或手动 `pip install -e .`。

注意：`quickstart.sh` 已经会负责“克隆相关仓库 + 创建 conda 环境 + 安装核心仓库 editable 包”。
不需要把“先建 conda，再手工去 `vllm-hust` 里装源码”当成默认主流程。

## 第 1 步：建立 Docker instance

`vllm-hust-dev-hub` 里的官方入口是：

- `scripts/ascend-official-container.sh`
- `ascend-runtime-manager` 的 `container` 子命令

如果你已经在目标机器上有可用容器，可直接跳到下一步。

### 方式 A：使用 quickstart 菜单 6 创建或复用容器

这是当前推荐入口，因为它会把容器启动、宿主机公钥采集和容器 SSH 配置串成一条路径。

在目标机器执行：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/quickstart.sh
```

然后在交互菜单选择：

```text
6) 创建/启动官方 Ascend Docker instance（可交互录入 SSH 公钥）
```

这一路径现在会自动完成这些事情：

- 可选地让你直接粘贴一个额外 SSH 公钥，并持久化到 `~/.ssh/vllm-ascend-extra-authorized_keys`
- 在检测到宿主机 SSH 公钥材料时自动配置容器内 `sshd`
- 自动对齐容器 SSH 用户和 `/workspace` 的 UID/GID，保证连上后能直接访问工作区
- 当工作区同级仓库是指向 `/data/...` 的 symlink 时，自动补挂真实目标路径
- 当 Docker 默认数据目录空间不够、而 `/data` 有空间时，自动迁移 Docker data-root 到 `/data/docker`

菜单 6 完成后，可继续使用：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh shell
```

### 方式 B：使用 hub 脚本创建或复用容器

在目标机器执行：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh start
```

需要直接进入容器时：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh shell
```

说明：

- 默认容器名是 `vllm-ascend-dev`
- 默认会按交互提示选择合适的官方镜像，当前默认是 `quay.io/ascend/vllm-ascend:v0.17.0rc1` 家族（A3 / openEuler 会自动切换对应后缀）。只有在你需要固定 openEuler、A3 或回归验证其他版本时，才需要额外设置 `export IMAGE=...`。
- 宿主机工作区根目录会挂载到容器内的 `/workspace`
- 容器内的默认工作目录是 `/workspace/vllm-hust-dev-hub`

### 方式 C：需要脚本化控制时，用 manager 做显式 `ssh-deploy`

如果需要在 CI、远程脚本或显式运维流程里跳过 quickstart 菜单，也可以直接执行：

```bash
cd /home/<your-user>/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/<your-user> \
  --ssh-user <your-user> \
  --ssh-port 2222
```

这一步会：

- 创建或启动官方 Ascend 容器
- 在容器里安装并启动 `sshd`
- 暴露容器 SSH 端口到宿主机，例如 `2222`
- 复制 `authorized_keys` 到容器用户目录

## 第 2 步：配置 SSH，连接 instance

默认开发流程里，连接容器所需配置是本地 `~/.ssh/config`，不是应用侧的 `config.ini` 或 `.env`。

如果宿主机已有可用的 SSH alias，推荐把容器 alias 配成经由宿主机自动跳转，而不是直接写公网 `2222`。这样即使公网侧没有开放 `2222`，VS Code Remote SSH 仍能直接进容器。

示例：

```sshconfig
Host train8
    HostName 11.11.10.27
    User <your-user>
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes

Host train8-container
    HostName 127.0.0.1
    User <your-user>
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

之后即可：

```bash
ssh train8-container
```

如果使用 VS Code，直接通过 Remote SSH 连接这个 host alias 即可。

如果容器刚被重建过，客户端可能缓存了旧的 host key。此时先清理旧记录再重连：

```bash
ssh-keygen -R train8-container
ssh-keygen -R "[127.0.0.1]:2222"
```

## 第 3 步：克隆 `vllm-hust-dev-hub`

在容器内或目标开发机上执行：

```bash
cd /home/<your-user>
git clone <your-vllm-hust-dev-hub-repo-url>
cd vllm-hust-dev-hub
```

说明：

- 推荐把仓库放在 `/home/<your-user>` 这一层
- `quickstart.sh` 会把其他相关仓库克隆为它的同级目录
- 不要求先进入 `scripts/` 目录，直接在仓库根目录运行 `bash scripts/quickstart.sh` 更直观

## 第 4 步：运行 quickstart，自动克隆相关仓库并建立 conda 环境

在 `vllm-hust-dev-hub` 根目录执行：

```bash
bash scripts/quickstart.sh
```

交互菜单请选择：

```text
1) Recommended bootstrap (sync repos + conda env)
```

这一步会自动完成：

- 同步/克隆常用工作区仓库
- 安装或检测 Miniconda
- 创建 `vllm-hust-dev` conda 环境（默认 Python 3.11）
- 安装基础工具：`pip`、`setuptools`、`wheel`、`pytest`、`pre-commit`
- 以 editable 方式安装核心本地仓库

默认会安装的核心仓库包括：

- `ascend-runtime-manager`
- `vllm-hust`
- `vllm-ascend-hust`
- `vllm-hust-benchmark`

如果机器检测到 Ascend 运行时，脚本还会调用 `hust-ascend-manager setup --install-python-stack` 做 Python 栈对齐。

如果本地缺少同级的 `vllm-ascend-hust` 仓库，quickstart 会自动回退到
PyPI 分发包 `vllm-ascend-hust`，通过 `hust-ascend-manager runtime repair --install-plugin`
完成插件安装和入口校验。

说明：

- 脚本会把 conda 自动激活逻辑写入 `~/.bashrc`
- `~/.bashrc` 的自动激活只对新的交互式 shell 生效，不会立刻改变当前正在运行的终端
- conda 环境激活时会自动探测 `https://hf-mirror.com`：可达则设置 `HF_ENDPOINT=https://hf-mirror.com`，不可达则自动回退默认 Hugging Face 上游
- 如需禁用上述自动镜像切换，可在当前 shell 设置 `HUST_DEV_HUB_DISABLE_HF_MIRROR_AUTOSET=1`
- `quickstart.sh` 只处理用户态环境，不会尝试 `sudo`、`sg`、`HwHiAiUser` 或其他系统级修改
- 相关上游对照仓库会被克隆到 `reference-repos/`，用于对比，不会自动安装进当前环境

补充说明：

- `Recommended bootstrap` 会执行完整的用户态 Python 环境准备，并在 Ascend 场景下做 Python 栈对齐
- 顶层的 `Refresh local repositories in existing env` 默认走 `refresh + core`，适合最常见的日常更新场景
- `Advanced options` 里仍然保留 conda-only、install-missing 和 bashrc-only 等低频操作
- 如果只是想补装或刷新仓库，同时希望把当前环境名写入 `~/.bashrc` 自动激活块，也可以直接运行 install-only 流程

如果某台宿主机还缺少系统级 Ascend 组件，或需要 `HwHiAiUser` 组权限，那是宿主机初始化问题，不属于 `quickstart.sh` 的职责范围。请单独使用 `hust-ascend-manager setup` 或宿主机运维流程处理。

### 非交互用法

如果希望一次性自动执行，可用：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/quickstart.sh --all -y
```

如果希望非交互地准备容器 SSH 公钥，可在运行菜单 6 之前设置：

```bash
export VLLM_HUST_CONTAINER_PUBKEY='ssh-ed25519 AAAA... your-name'
```

## 第 5 步：进入 conda 环境，并按需继续安装或刷新源码

### 默认推荐

优先检查 `quickstart.sh` 是否已经完成安装，而不是一上来手动重装。

新开一个 shell 后通常会自动进入：

```bash
conda activate vllm-hust-dev
```

可用以下命令验证环境：

```bash
conda run -n vllm-hust-dev vllm --help
```

### 什么时候还需要再次执行 `quickstart.sh`

以下情况建议继续使用 hub 脚本，而不是手工逐仓库安装：

- 第一次安装中断，需要补装缺失仓库
- `git pull` 后需要刷新 editable 安装
- 想把额外本地仓库也一起装进环境

命令示例：

```bash
cd /home/<your-user>/vllm-hust-dev-hub

# 只安装当前环境里缺失的本地仓库
bash scripts/quickstart.sh --install --env-name vllm-hust-dev -y

# 强制刷新核心仓库的 editable 安装
bash scripts/quickstart.sh --install --install-mode refresh --env-name vllm-hust-dev -y

# 刷新核心仓库 + 额外本地仓库
bash scripts/quickstart.sh --install --install-mode refresh --install-scope full --env-name vllm-hust-dev -y
```

### 什么时候可以手工 `pip install -e .`

只有在以下场景才建议手工执行：

- 只想重装某一个仓库
- 正在调试某个仓库自己的依赖安装问题
- 不希望由 hub 脚本统一处理整套工作区

示例：

```bash
conda activate vllm-hust-dev

cd /home/<your-user>/vllm-hust
python -m pip install -e .

cd /home/<your-user>/vllm-ascend-hust
python -m pip install -e .
```

注意：这不是团队默认推荐主流程，只是补充手段。

## 团队统一推荐流程

建议对团队成员直接发下面这版简化流程：

```text
1. 在目标机器上执行 `bash scripts/quickstart.sh`，菜单选择 6 创建或复用官方 Ascend Docker 容器。
2. 如果需要从本地直连容器，在菜单 6 中粘贴 SSH 公钥，然后在本地 `~/.ssh/config` 增加经由宿主机 `ProxyJump` 的容器别名。
3. 在容器内克隆 vllm-hust-dev-hub 到 /home/<user>/vllm-hust-dev-hub。
4. 在仓库根目录执行 bash scripts/quickstart.sh。
5. 菜单选择 Recommended bootstrap (sync repos + conda env)。
6. 完成后进入 conda activate vllm-hust-dev。
7. 如需补装或刷新源码，优先再次运行 quickstart.sh --install；只有特殊情况再手工 pip install -e .。
```

## 可选：vllm-hust-workstation

`vllm-hust-workstation` 是独立应用，不属于默认开发环境主流程。

只有在需要联调或运行这个应用时，才需要额外配置：

```bash
cd /home/<your-user>/vllm-hust-workstation
cp .env.example .env
```

至少确认以下字段：

```dotenv
VLLM_HUST_BASE_URL=http://localhost:8080
VLLM_HUST_API_KEY=not-required
DEFAULT_MODEL=Qwen2.5-7B-Instruct
```

如果 `VLLM_HUST_BASE_URL` 指向远端服务，`vllm-hust-workstation/quickstart.sh` 会按远端模式处理，不会在本机自动拉起服务。

## 常见问题

### 1. 必须先 `cd scripts/` 吗？

不需要。推荐在仓库根目录执行：

```bash
cd /home/<your-user>/vllm-hust-dev-hub
bash scripts/quickstart.sh
```

### 2. `quickstart.sh` 会不会自动安装源码？

会。默认 conda 环境创建完成后，会自动把核心仓库以 editable 方式安装进去。

### 3. `quickstart.sh` 会不会再尝试改系统环境？

不会。`quickstart.sh` 现在只负责用户态 conda 环境、Python 栈和本地 editable 安装。

如果宿主机还需要安装系统级 Ascend 组件、切换组权限或做运维初始化，需要单独执行 `hust-ascend-manager setup` 或走宿主机初始化流程。

### 4. `reference-repos/*` 会装进环境吗？

不会。它们只用于上游对照和同步分析。

### 5. 一定要手工 `pip install -e .` 吗？

不一定。大多数成员只需要跑完 `quickstart.sh` 即可。

### 6. 容器和工作站配置是同一个 config 文件吗？

不是。

- 连接容器看的是本地 `~/.ssh/config`
- 连接 `vllm-hust` 服务实例看的是 `vllm-hust-workstation/.env`
- `config.ini.example` 属于旧的 Python server 路径，不建议放进默认 onboarding 主流程
