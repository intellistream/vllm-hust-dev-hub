# train8 官方 Ascend 容器运维手册

本文面向需要在 `train8` 上长期维护官方 Ascend 开发容器的同学，目标不是一次性“跑起来”，而是把镜像选型、首次部署、SSH 接入、例行巡检、故障处理和回滚路径都讲清楚。当前默认基线已切换到 `quay.io/ascend/vllm-ascend:v0.17.0rc1` 家族，对应当前 `vllm-ascend-hust` 使用的 CANN 8.5.1 运行时预期。

## 1. 适用范围

适用于以下场景：

- 在 `train8` 上创建或接管官方 Ascend Docker 开发容器
- 从 Windows 或 Linux 客户端直接 SSH 进入容器
- 在容器中执行 `vllm-hust` / `vllm-ascend-hust` 开发、联调、分布式测试
- 需要保证 HCCL、多卡 `torch.distributed`、vLLM 多 NPU 运行不被 Docker bridge 网络破坏

不适用于以下场景：

- 需要完全自定义基础镜像并自行维护驱动映射
- 需要脱离 `ascend-runtime-manager` 直接手写长 `docker run` 命令

## 2. 基线约定

当前推荐基线如下：

- 910B / Ubuntu: `quay.io/ascend/vllm-ascend:v0.17.0rc1`
- 910B / openEuler: `quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler`
- 910C / A3 / Ubuntu: `quay.io/ascend/vllm-ascend:v0.17.0rc1-a3`
- 910C / A3 / openEuler: `quay.io/ascend/vllm-ascend:v0.17.0rc1-a3-openeuler`

运行特性：

- manager 容器流程默认使用 `--net=host`
- 宿主机工作区根目录挂载到容器内 `/workspace`
- 容器名默认是 `vllm-ascend-dev`
- 容器内默认工作目录是 `/workspace/vllm-hust-dev-hub`
- SSH 服务直接监听宿主机端口，例如 `2222`，不是 Docker `-p` 端口映射

这意味着：

- HCCL、多卡集合通信、机器内联调都应沿用宿主机网络拓扑
- 容器 SSH 端口冲突要按宿主机端口占用来处理
- 如果对外网络不开放 `2222`，优先用 `ProxyJump` 从宿主机跳进容器

## 3. 部署前检查

首次部署前先在 `train8` 宿主机确认下面几项：

```bash
docker --version
docker ps >/dev/null
npu-smi info
whoami
pwd
df -h /
df -h /data
```

建议检查点：

- 当前账号能直接运行 `docker`；如果不能，至少要支持 `sudo -n docker`
- `npu-smi info` 能正常列出设备
- `/data` 还有足够空间给 Docker 镜像和容器层使用
- 工作区父目录下已经有需要挂载进容器的仓库，例如 `/home/shuhao/vllm-hust`

如果宿主机 `/var/lib/docker` 空间不足，但 `/data` 空间充足，可让 quickstart/helper 迁移 Docker data-root 到 `/data/docker`，再重新拉镜像。

## 4. 推荐部署方式

### 4.1 方式 A：通过 quickstart 菜单一键创建

这是团队默认推荐路径，适合首次部署和人工运维。

在 `train8` 宿主机执行：

```bash
cd /home/shuhao/vllm-hust-dev-hub
bash scripts/quickstart.sh
```

然后选择：

```text
6) 创建/启动官方 Ascend Docker instance（可交互录入 SSH 公钥）
```

这个流程会做以下事情：

- 检测或创建 `vllm-ascend-dev` 容器
- 交互式选择官方镜像变体；未额外指定时默认从 `v0.17.0rc1` 家族中按设备和 OS 选型
- 允许粘贴额外公钥，并保存到 `~/.ssh/vllm-ascend-extra-authorized_keys`
- 在容器内安装并配置 `openssh-server`
- 将容器 SSH 用户与 `/workspace` 的挂载所有权对齐，避免登录后工作区不可写
- 处理 `/data/...` 形式的外部软链接挂载，保证容器内路径可达

如果你明确知道自己需要 openEuler 或 A3 变体，也可以在运行前固定镜像：

```bash
export IMAGE=quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler
bash scripts/quickstart.sh
```

### 4.2 方式 B：通过 manager 显式 `ssh-deploy`

适合自动化脚本、远程代运维或需要把命令记录进 SOP 的场景。

```bash
cd /home/shuhao/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 2222
```

如果你要固定某个镜像变体，再补一个环境变量：

```bash
export IMAGE=quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 2222
```

该命令会：

- 拉取缺失镜像
- 创建或启动官方容器
- 配置容器内 `sshd`
- 将 `authorized_keys` 同步到容器用户家目录
- 通过宿主机网络直接暴露容器 SSH 端口
- 确保容器重启后仍然能恢复 SSH 服务

## 5. 客户端 SSH 配置

建议保留两个 SSH 别名：

- `train8`：连接宿主机
- `train8-container`：经宿主机跳转进入容器

Windows 或 Linux 客户端都可以使用类似配置：

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

说明：

- 保持 `train8` 继续用于宿主机管理
- `train8-container` 通过 `ProxyJump train8` 进入容器，适合外网不开放 `2222` 的情况
- 如果你在部署时改了 `--ssh-port`，这里的 `Port` 也要同步修改

## 6. 首次登录后的验收

首次 `ssh train8-container` 登录后，至少执行以下检查：

```bash
python -c "import torch; import torch_npu; print(torch.npu.device_count())"
python -c "import os; print(os.environ.get('ASCEND_HOME_PATH', '<unset>'))"
which npu-smi || true
npu-smi info
```

期望结果：

- `torch_npu` 可导入
- `torch.npu.device_count()` 返回正确设备数
- `ASCEND_HOME_PATH` 已设置
- `npu-smi info` 在容器内可用

如果你要做分布式或 HCCL 联调，再补一个网络侧检查：

```bash
python -c "import socket; print(socket.gethostname())"
ls -l /usr/local/Ascend/driver/tools/hccn_tool || true
```

## 7. 日常运维命令

进入容器交互 shell：

```bash
cd /home/shuhao/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh shell
```

启动或复用容器：

```bash
cd /home/shuhao/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh start
```

执行一次性命令：

```bash
cd /home/shuhao/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container exec -- \
  bash -lc 'python -c "import torch; import torch_npu; print(torch.npu.device_count())"'
```

宿主机直接检查容器状态：

```bash
docker ps --filter name=vllm-ascend-dev
docker logs --tail 50 vllm-ascend-dev
```

## 8. 常见变更操作

### 8.1 修改 SSH 端口

如果宿主机 `2222` 已被占用，重新部署时换一个端口：

```bash
cd /home/shuhao/ascend-runtime-manager
PYTHONPATH=src python3 -m hust_ascend_manager.cli container ssh-deploy \
  --host-workspace-root /home/shuhao \
  --ssh-user <ssh-user> \
  --ssh-port 22022
```

然后同步更新客户端 `train8-container` 的 `Port`。

### 8.2 切换镜像变体

例如从 Ubuntu 切到 openEuler：

```bash
cd /home/shuhao/vllm-hust-dev-hub
export IMAGE=quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler
bash scripts/ascend-official-container.sh rm
bash scripts/ascend-official-container.sh start
```

如果是通过 manager 维护，也可以在 `ssh-deploy` 前设置同样的 `IMAGE`。

### 8.3 回归验证旧版本镜像

仅在兼容性排查或历史复现时这样做：

```bash
export IMAGE=quay.io/ascend/vllm-ascend:<old-tag>
```

然后重新创建容器。完成验证后应切回 `v0.17.0rc1` 家族，以免和当前 `vllm-ascend-hust` 的 CANN 8.5.1 预期脱节。

## 9. 故障排查

### 9.1 SSH 连不上容器

先在宿主机检查：

```bash
docker ps --filter name=vllm-ascend-dev
ss -ltnp | grep 2222 || true
docker exec vllm-ascend-dev ps -ef | grep sshd
```

排查重点：

- 容器是否实际在运行
- `sshd` 是否已启动
- 端口是否已被别的进程占用
- 客户端是否仍缓存旧 host key

如果是 host key 冲突，客户端执行：

```bash
ssh-keygen -R train8-container
ssh-keygen -R "[127.0.0.1]:2222"
```

### 9.2 容器里看不到 NPU

在宿主机和容器内分别执行：

```bash
npu-smi info
docker exec vllm-ascend-dev bash -lc 'npu-smi info'
```

如果宿主机正常、容器异常，通常要检查：

- manager 是否按预期挂载了 Ascend 设备和驱动目录
- 容器是否被手工删除后又用非 manager 命令重建
- 选用的镜像是否和当前宿主机 OS / 设备类型严重不匹配

### 9.3 CANN 版本不对

在容器内检查：

```bash
cat /usr/local/Ascend/ascend-toolkit/latest/runtime/version.info || true
cat /usr/local/Ascend/ascend-toolkit/latest/compiler/version.info || true
```

如果不是 8.5.1 对应版本，优先确认当前镜像 tag：

```bash
docker inspect vllm-ascend-dev --format '{{.Config.Image}}'
```

当前默认应落在 `v0.17.0rc1` 家族；若看到旧 tag，说明该容器是旧时期创建的，需要重建。

### 9.4 HCCL / 多卡通信异常

先确认不是 Docker bridge 网络问题。本手册的 manager 流程默认使用 `--net=host`，如果你是手工起了另一个容器，极可能是网络模式不一致。

建议检查：

- 当前目标容器是否确实由 manager/quickstart 创建
- 容器是否仍保留 host networking
- 宿主机 HCCL 所需工具链和驱动路径是否完整

### 9.5 拉镜像失败或磁盘不足

检查：

```bash
df -h /
df -h /data
docker system df
```

如果 `/var/lib/docker` 太小且 `/data` 空间足够，按团队约定迁移 data-root 到 `/data/docker` 后再重试。

## 10. 回滚与重建

当容器状态不可信、镜像混乱、SSH 配置污染严重时，不要在旧容器上继续修补，直接重建：

```bash
cd /home/shuhao/vllm-hust-dev-hub
bash scripts/ascend-official-container.sh rm
bash scripts/ascend-official-container.sh start
```

如果你需要重新打通 SSH，再执行 quickstart 菜单或 manager `ssh-deploy`。

重建前建议保留的信息：

- 当前使用的 `IMAGE`
- 当前 `--ssh-port`
- 是否额外挂载了自定义路径

## 11. 建议运维习惯

- 平时用 `train8` 管宿主机，用 `train8-container` 进容器，职责分开
- 修改镜像 tag、SSH 端口、OS 变体时，记录到值班笔记或交接文档
- 做多卡训练或 serving 前，先跑一次容器内 NPU/网络健康检查
- 不要手工 `docker run` 一个同名替代容器，否则后续 manager 的状态判断会失真