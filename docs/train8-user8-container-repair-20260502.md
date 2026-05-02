# train8 user8 Docker 实例修复纪要（2026-05-02）

本文记录一次针对 `train8` 上 `user8` 账号开发容器的现场修复过程，重点回答两个问题：

- 原来的实例为什么不满足当前 `vllm-ascend-hust` 要求
- 这次是如何在不破坏现场可回滚性的前提下，把实例修到可用状态的

这不是通用入门手册，通用流程仍以 [train8-container-quickstart.md](train8-container-quickstart.md) 为准；本文是一次真实现场处置的操作纪要。

## 1. 背景

目标是修复 `train8` 上 `user8` 当前在用的 Docker 开发实例，使其满足当前 `vllm-ascend-hust` 所依赖的 CANN 8.5.1 基线，并恢复直接 SSH 进入容器的能力。

修复前已知目标：

- 宿主机是 `train8`
- 待修复账号是 `user8`
- 当前 fork 文档要求官方 Ascend 容器基线对齐 CANN 8.5.1
- 本地代码侧已经把默认镜像基线更新为 `v0.17.0rc1` 家族

## 2. 初始现场状态

首次登录宿主机后，先确认了两件事：

1. 宿主机本身仍是 `cann-8.5.0`
2. `user8` 当前在用的容器不是标准 `vllm-ascend-dev`，而是历史容器 `user8-vllm-dev`

现场发现：

- 标准容器名 `vllm-ascend-dev` 不存在
- `user8-vllm-dev` 使用镜像 `quay.io/ascend/vllm-ascend:v0.13.0-openeuler`
- `user8-vllm-dev` 容器内 `ascend-toolkit/latest/compiler/version.info` 显示 `Version=8.5.0`
- 因此当前实例与目标的 CANN 8.5.1 基线不一致

同时还能看到宿主机上存在一些别的历史容器和镜像，包括：

- `flj_base`
- `vllm0.18`
- `quay.io/ascend/vllm-ascend:nightly-releases-v0.18.0-openeuler`

## 3. 诊断过程

这次修复不是直接“一键重建”，而是先排除现场阻塞因素。

### 3.1 确认旧实例问题

对 `user8-vllm-dev` 做了以下检查：

- `docker inspect`
- 容器内 CANN 版本检查
- 工作目录和挂载路径检查

结论：

- 该容器仍停留在 `v0.13.0-openeuler`
- 容器内仍是 `8.5.0`
- 不满足当前 `vllm-ascend-hust` 对 8.5.1 的预期

### 3.2 尝试按新目标镜像直接修复

原计划是直接按最新文档目标，拉起：

- `quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler`

现场也确实尝试过：

- 用 `vllm-hust-dev-hub/scripts/ascend-official-container.sh`
- 显式传入 `IMAGE=quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler`
- 使用 `user8`、`2222`、非交互参数执行 `ssh-deploy`

但结果是：

- 镜像拉取在大层下载后进入长时间阻塞
- 无法在合理时间内完成现场切换

因此没有继续死等，而是转为查找“本机已有、且已经满足 8.5.1”的替代镜像。

### 3.3 发现可直接复用的本地镜像

对宿主机现有镜像和容器做盘点后，发现：

- 宿主机已有 `quay.io/ascend/vllm-ascend:nightly-releases-v0.18.0-openeuler`
- 该镜像对应的现场容器 `flj_base` 中，`ascend-toolkit/latest/compiler/version.info` 显示 `Version=8.5.1`

这说明：

- 不必继续卡在 `v0.17.0rc1-openeuler` 的慢拉取上
- 可以直接用本机已有的 `nightly-releases-v0.18.0-openeuler` 完成本次实例修复
- 虽然它不是文档里首选的 `v0.17.0rc1`，但它在当前现场满足最关键的目标：CANN 8.5.1

### 3.4 发现远端 manager 还有两个额外问题

现场还确认了两个容易让后续自动化再次失败的问题：

1. `train8` 上系统 Python 是 `3.9.9`
2. `/home/user8/ascend-runtime-manager` 的源码运行依赖 `dataclass(slots=True)`，直接用系统 Python 会报错

此外还有一个 SSH 配置问题：

- `nightly-releases-v0.18.0-openeuler` 镜像中不存在 `/etc/ssh/sshd_config.d`
- 导致 manager 的 `ssh-deploy` 在写 `vllm-ascend.conf` 时失败

这也是为什么后半程不能完全依赖远端 manager 自动收尾，而必须手工补一层容器内 SSH 配置。

## 4. 实际修复动作

### 4.1 先保留回滚点

没有直接覆盖原实例，而是先把旧容器重命名并停掉：

- 原容器：`user8-vllm-dev`
- 备份容器：`user8-vllm-dev-bak-20260501`

这样做的目的：

- 如果新实例行为异常，可以立刻回滚到旧容器
- 不丢失旧容器内现场环境

### 4.2 用本地已存在的 8.5.1 镜像重建同名实例

新实例仍保留原来的容器名 `user8-vllm-dev`，但镜像切换为：

- `quay.io/ascend/vllm-ascend:nightly-releases-v0.18.0-openeuler`

执行时显式指定：

- `CONTAINER_NAME=user8-vllm-dev`
- `DEFAULT_CONTAINER_SSH_USER=user8`
- `DEFAULT_CONTAINER_SSH_PORT=2222`
- 工作区根目录挂载为 `/home/user8 -> /workspace`

重建后确认到的新实例属性：

- 镜像：`nightly-releases-v0.18.0-openeuler`
- 工作目录：`/workspace/vllm-hust-dev-hub`
- 缓存挂载：`/home/user8/.cache -> /root/.cache`
- 设备/驱动挂载按 manager 规则生效

### 4.3 手工补齐容器内 SSH

第一次 `ssh-deploy` 没有完全成功，失败点是：

- `/etc/ssh/sshd_config.d/vllm-ascend.conf: No such file or directory`

因此后续改为手工在容器内做以下动作：

- 创建 `/etc/ssh/sshd_config.d`
- 确保 `user8` 用户存在且与 `/workspace` UID/GID 对齐
- 复制 `/workspace/.ssh/vllm-ascend-authorized_keys.auto` 到容器用户家目录
- 生成主机密钥
- 写入 `Port 2222`、`AllowUsers user8`、`AuthorizedKeysFile .ssh/authorized_keys` 等 SSH 配置
- 启动 `/usr/sbin/sshd`

补完后，从宿主机本地回环验证：

- `ssh -p 2222 user8@127.0.0.1`

验证通过。

## 5. 修复后状态

最终状态如下：

- 新实例：`user8-vllm-dev`
- 备份实例：`user8-vllm-dev-bak-20260501`
- 新实例镜像：`quay.io/ascend/vllm-ascend:nightly-releases-v0.18.0-openeuler`
- 新实例状态：`Up`
- 旧实例状态：`Exited`

关键验证结果：

- 容器内 CANN：`Version=8.5.1`
- 容器内 NPU 可见数：`8`
- 宿主机端口监听：`2222`
- 宿主机本地回环 SSH：成功返回 `user8`

## 6. 为什么这次没有强行落到 v0.17.0rc1

严格说，这次修复“实例现场”时没有最终落在 `v0.17.0rc1-openeuler`，原因只有一个：

- 现场拉取 `v0.17.0rc1-openeuler` 时在 registry/大层下载阶段长时间阻塞，无法在本次会话里稳定完成切换

但本次修复仍然达成了核心目标：

- 把原来的 `8.5.0` 容器换成了 `8.5.1` 容器
- 恢复了 SSH 直连能力
- 保留了旧容器回滚点

因此这次处置属于“现场优先恢复可用性”的修复，而不是“完全对齐最新默认 tag”的收尾。

## 7. 后续建议

这次修完后，建议再补三件事：

### 7.1 同步远端代码到最新默认逻辑

`train8` 上 `user8` 本地的这两个仓库应尽快同步：

- `/home/user8/ascend-runtime-manager`
- `/home/user8/vllm-hust-dev-hub`

目标是让远端默认逻辑也切到 `v0.17.0rc1`，避免下次执行 `ssh-enable` / `ssh-deploy` 时又回落到旧 tag。

### 7.2 统一远端 Python 执行环境

现场系统 Python 是 `3.9.9`，对当前 manager 源码不够新。建议明确约定：

- 远端执行 manager 时统一走 `miniconda3/bin/python`

否则后续直接跑源码命令时还会再次碰到 dataclass 参数不兼容问题。

### 7.3 评估是否要继续把实例换到 v0.17.0rc1-openeuler

如果后续 registry 拉取恢复正常，仍建议补做一次正式切换，把 `user8-vllm-dev` 从 `nightly-releases-v0.18.0-openeuler` 切到文档默认目标：

- `quay.io/ascend/vllm-ascend:v0.17.0rc1-openeuler`

这样现场实例与当前仓库文档、默认值、运维预期会完全一致。

## 8. 一句话结论

这次修复的核心做法不是“硬顶着最新目标镜像拉完”，而是：先确认旧实例确实卡在 `8.5.0`，再利用宿主机上已经存在的 `8.5.1` 镜像快速完成实例替换，最后手工补齐容器内 SSH，把现场恢复到可直接开发、可直接登录、且可回滚的状态。