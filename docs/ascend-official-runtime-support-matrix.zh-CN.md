# Ascend 官方运行环境支持矩阵

> 基准日期：2026-09-01（Asia/Shanghai）  
> 机器真源：[config/ascend-official-runtime-matrix.json](../config/ascend-official-runtime-matrix.json)  
> 自动核验：`python3 scripts/verify_ascend_runtime_matrix.py --all`

## 结论与使用边界

当前批准基线是 vLLM Ascend `v0.23.0` 正式版。官方 Quay 仓库提供 4 类硬件、2 类基础 OS，共 8 个正式 tag；每个 tag 都是同时包含 `linux/arm64` 和 `linux/amd64` 的 OCI image index。本表只批准 `linux/arm64` 子 manifest，部署时必须同时固定顶层 index digest 和记录 ARM64 manifest digest。

`main`、`nightly-*`、`*-dev*`、模型专用 tag 和旧 RC 虽然仍可在 Quay 枚举或下载，但它们是可变、过期或用途受限的发现项，不属于组织批准基线。区域镜像仅可作为传输缓存，不能替代 Quay digest 作为身份依据。

统一软件栈如下：CANN `9.1.0`、Torch `2.10.0`、torch-npu `2.10.0.post4`、Python `3.12.13`、vLLM `0.23.0`、vLLM Ascend `0.23.0`；A2/A3/Ascend 950 使用 Triton Ascend `3.2.2`，310P 不支持并在官方镜像中卸载 Triton。正式 release note、镜像 Dockerfile 和实际 ARM64 image config 三方一致。

上游 v0.23.0 tag 对应 core commit `0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665`、plugin commit `5cb98caaadeff42b5b62b996e34bb2aaa29d20fd`。但镜像没有 `org.opencontainers.image.revision` 或可验证构建证明，因此这是“官方 release 引用 commit”，不能表述为镜像字节对源码 commit 的密码学证明。

**源码身份边界：**当前 `vllm-hust` 与 `vllm-ascend-hust` 均已从对应官方上游直接重建，分别以 `vllm-project/vllm` 和 `vllm-project/vllm-ascend` 为源码根。不得再用重建前的独立 fork 历史描述当前仓库，也不得把重建前的 commit 当成当前验证 commit。每次验收使用的组织仓库 commit 都必须能从重建后的上游根谱系解析和审计。

## 重建后重新盘点结论

稳定镜像清单没有失效，但“镜像适配哪一组源码”的关系必须重建。2026-09-01 复查时，组织仓库与上游仍在继续同步；`main` 是移动目标，分支名不能作为可复现身份。

| 源码组合 | 精确身份 | 对应官方镜像 | 状态与处置 |
|---|---|---|---|
| v0.23.0 稳定发布 | core `0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665`；plugin `5cb98caaadeff42b5b62b996e34bb2aaa29d20fd` | 下表 8 个 v0.23.0 digest | **官方验证**；唯一批准的稳定 source/image profile |
| HUST main 复查快照 | core `ed9f108ad80f4d8f058cf35541c785452c1c48ef`，功能上游父提交 `754d5e1f6597f0742f8fb8f7325533e5db37ae23`；plugin `660da858686d1a09545ca70831f8f47ac6d65fe6`，功能上游父提交 `72a988f9d33f392abf85e6059e2e37dc2d48c482` | **无精确对应的稳定镜像** | **尚未验证**；需要固定 commit、重新构建 native/custom-op 扩展并做真实 NPU 验收 |
| plugin main Docker 候选 | vLLM `v0.27.1`（`6e448d0ea9bf3d88d898b65449ca6dc2aec170ac`）+ plugin `660da858…` | 只有 nightly 候选，没有 vLLM Ascend v0.27.1 稳定 release | **官方开发候选 / 尚未验证**；不得标成稳定组合 |

当前 plugin 快照固定 CANN `9.1.0`、Torch `2.10.0`、torch-npu `2.10.0.post4`、Triton Ascend `3.2.2`（310P 除外）和 Python 3.12；其 Dockerfile 默认 `VLLM_TAG=v0.27.1`。当前 core 快照的构建隔离配置请求 Torch `2.13.0`，但 Ascend overlay 以 `VLLM_TARGET_DEVICE=empty` 构建，运行时 Torch 由 plugin 环境提供。因此这是一项必须通过构建和实机测试确认的 build/runtime 分层，不能仅凭两个 Torch 数字断言运行时硬冲突。

禁止把当前 HUST main 直接覆盖到 v0.23.0 稳定镜像后沿用旧验证状态。若组织需要 main 验证通道，应建立独立派生镜像、记录完整 core/plugin commit 和派生镜像 digest，并从“尚未验证”重新开始。

## ARM64 正式镜像

状态含义：

- **官方验证**：上游正式发布并列入该硬件支持范围。
- **社区验证**：vLLM-HUST 在真实 NPU 上保存了可追溯证据；它不会覆盖官方状态。
- **尚未验证**：组织尚无对应 OS/ARM64/NPU 组合的真实设备证据。

| NPU / OS | 官方 tag | 不可变 index digest | ARM64 manifest digest | 最低 Driver / Firmware | Triton | 上游 / HUST 状态 | core / plugin commit |
|---|---|---|---|---|---|---|---|
| A2 / Ubuntu 22.04 | `v0.23.0` | `sha256:471744200c5d0c768c1f6c6a6816dcae0fd551de2487d4d129b6fb750024ce6a` | `sha256:4ee78def8f33d59d48f116d1dfa793332c23c99ecab4f0d7dd5cd62d0fb4e6c1` | Driver `26.0.RC1`；同产品 26.0.RC1 HDK 配套固件 | 3.2.2 | 官方验证 / 尚未验证 | `0fc695f` / `5cb98ca` |
| A2 / openEuler 24.03 | `v0.23.0-openeuler` | `sha256:b2d13e24b295171d8f63678506fad5542f142e81d57e407a0b8c98c16ba0c4f7` | `sha256:6c183dfa86cf13ea5fa54ac8f0bcf7316c5b91e7f9774c26dc282dfd94da8ef9` | Driver `26.0.RC1`；同产品 26.0.RC1 HDK 配套固件 | 3.2.2 | 官方验证 / **尚未验证（重建后）** | 官方 `0fc695f` / `5cb98ca`；当前 HUST commit 待实机验收 |
| A3 / Ubuntu 22.04 | `v0.23.0-a3` | `sha256:8e931f2a1908f4213ec31a349d5263a19c480e2e1e2dda801fdc35dd6ab279a5` | `sha256:96e4a97fce24262aee2dbcc6e81cb2655c45784c1a28450cb7c1114b0d05989e` | Atlas A3 Driver `26.0.RC1`；同产品 HDK 配套固件 | 3.2.2 | 官方验证 / 尚未验证 | `0fc695f` / `5cb98ca` |
| A3 / openEuler 24.03 | `v0.23.0-a3-openeuler` | `sha256:382b012420854ba2d8b3b78897d9216742f27948345e503a01644ebbdd706ce6` | `sha256:d71b467a10e2aba2462a0d0fb020cbb3de8d46fbcd2f450c44e8614eeb4e7ed0` | Atlas A3 Driver `26.0.RC1`；同产品 HDK 配套固件 | 3.2.2 | 官方验证 / 尚未验证 | `0fc695f` / `5cb98ca` |
| Ascend 950 / Ubuntu 22.04 | `v0.23.0-a5` | `sha256:cc57064f119054904dc81360cd1105d211fa9b91bf726486926dd025c26f17b7` | `sha256:4bab0e083fa9e73058c9a5e04862a5f52c6e0820d06bc5888c9e5628bc199987` | Atlas A5 Driver `25.7.RC1`；同产品 HDK 配套固件 | 3.2.2 | 官方验证 / 尚未验证 | `0fc695f` / `5cb98ca` |
| Ascend 950 / openEuler 24.03 | `v0.23.0-a5-openeuler` | `sha256:28998d3626c6a74ca5625c5d41747bd7ae8b410e02134e1dd7f45e2eb99c17b6` | `sha256:c081ad9ec89af3c97be78c655c8ccba1a37ef2107cb07d1bfed1eb2caf156192` | Atlas A5 Driver `25.7.RC1`；同产品 HDK 配套固件 | 3.2.2 | 官方验证 / 尚未验证 | `0fc695f` / `5cb98ca` |
| 310P / Ubuntu 22.04 | `v0.23.0-310p` | `sha256:027965d4b81d7e33e3208a47d5ff85a5f26a0e2866875b95eafae844e90fd082` | `sha256:796976f38ac2176bf77f1d12398d80a1238291f4cdd8e7d284e7f4129fdbfcb5` | Ascend 310P Driver `26.0.RC1`；同产品 HDK 配套固件 | 不支持 | 官方验证（硬件实验性）/ 尚未验证 | `0fc695f` / `5cb98ca` |
| 310P / openEuler 24.03 | `v0.23.0-310p-openeuler` | `sha256:12f4cc51a470dcf1c6142e7865783d47efad3803971eb760445cb0796946f0e6` | `sha256:ffeb177dd585f567036f0a51a76adc6e109599f705385fbe66652d9fe76431ab` | Ascend 310P Driver `26.0.RC1`；同产品 HDK 配套固件 | 不支持 | 官方验证（硬件实验性）/ 尚未验证 | `0fc695f` / `5cb98ca` |

适用型号按上游口径：A2 包括 Atlas A2 训练系列和 Atlas 800I A2 推理系列；A3 包括 Atlas A3 训练系列和 Atlas 800I A3 推理系列；`-a5` 对应 Ascend 950 系列；`-310p` 主要对应 Atlas 300I DUO，Atlas 200I Pro 还需要官方安装文档列出的额外设备节点和驱动挂载。Ascend 910/910 Pro B 与 Atlas 200I A2（310B）当前不在上游支持范围。

## 下载与安装

官方镜像下载地址是 [Quay vLLM Ascend tags](https://quay.io/repository/ascend/vllm-ascend?tab=tags)。不要把网页镜像、个人网盘、群文件或只有 tag 没有 digest 的转存包登记为来源。

每条记录的完整命令都在 JSON 的 `install` 字段中。通用形式是：

```bash
docker pull --platform linux/arm64 \
  quay.io/ascend/vllm-ascend@sha256:<该行的完整-index-digest>
```

在本仓库的 A2/openEuler 默认环境中：

```bash
IMAGE=quay.io/ascend/vllm-ascend@sha256:b2d13e24b295171d8f63678506fad5542f142e81d57e407a0b8c98c16ba0c4f7 \
  bash scripts/ascend-official-container.sh start
```

tag 便于人读，digest 才是部署身份。拉取后同时保存：

```bash
docker image inspect \
  quay.io/ascend/vllm-ascend@sha256:<index-digest> \
  --format '{{json .RepoDigests}} {{.Architecture}} {{.Os}}'
```

## Nightly 发现快照（不批准部署）

以下记录用于发现缺失架构和构建漂移，不是推荐组合。nightly tag 可随时重指向；表中 digest 只是 2026-09-01 的不可变快照。

| Tag | OS / NPU | 当时平台 | digest | 从 config/history 观察到的 vLLM | 状态 |
|---|---|---|---|---|---|
| `nightly-main` | Ubuntu / A2 | ARM64 | `sha256:e72301ee566d6cf941ac242bf5731314e72ecfa9270066f9de941f3aad5c737b` | v0.27.1 | 尚未验证 |
| `nightly-main-openeuler` | openEuler / A2 | ARM64 + AMD64 | `sha256:933b77f733a69f7b4adb79c8e1d52f22549b8c3553e828ca9d790a7f62b2e2e1` | v0.26.0 | 尚未验证；旧于 Ubuntu 构建 |
| `nightly-main-a3` | Ubuntu / A3 | ARM64 | `sha256:59de2163723ea5fc7d2a64f85f8d49c71f4aebac8a9c20f91628d455f17868e7` | v0.27.1 | 尚未验证 |
| `nightly-main-a3-openeuler` | openEuler / A3 | ARM64 + AMD64 | `sha256:5ec3e4bd79931d8fe39ba5670cab9a9d71d41e61d2274c391bd0a6e4e653b4dc` | v0.26.0 | 尚未验证；旧于 Ubuntu 构建 |
| `nightly-main-a5` | Ubuntu / A5 | **仅 AMD64** | `sha256:96491947bdbe6285d1f1d270721b357fc7849efa2aea590561bc54c91d308da0` | v0.27.1 | **缺 ARM64** |
| `nightly-main-a5-openeuler` | openEuler / A5 | ARM64 + AMD64 | `sha256:8865cd8fd015f5bb94caf3c9db2f3aea932d1f89d5f8b79f8e255099e6e54699` | v0.26.0 | 尚未验证；旧于 Ubuntu 构建 |
| `nightly-main-310p` | Ubuntu / 310P | ARM64 | `sha256:3a7d83ca7eb265e53ab781982271b46c22b3caf144c0a623ede81d490e498206` | v0.27.1 | 尚未验证 |
| `nightly-main-310p-openeuler` | openEuler / 310P | ARM64 + AMD64 | `sha256:2b1a8113b40ce2b83c4732a1c1888d5c488ea8a7c00d7d144d5555267f376b12` | v0.26.0 | 尚未验证；旧于 Ubuntu 构建 |

Ubuntu nightly 当前是单平台 Docker manifest，而 openEuler nightly 是多平台 OCI index。校验脚本同时支持这两种格式；若可变 tag 已漂移，会失败并要求人工复盘，不会自动接受新 digest。

这些 nightly 的 OCI metadata 没有给出可核验的 core/plugin commit，也没有完整证明 Torch、torch-npu、Triton Ascend 与 Python 包版本；清单相应字段明确为 `null` 或“未证明”。表中的 vLLM ref 来自 config history，不等同于源码构建证明。任何试用都必须先按 digest 拉取、进入容器采集 `pip freeze` 与 git identity，再执行对应硬件的 Driver/Firmware 和真实 NPU 验收。

## 官方来源、许可证与访问限制

- [v0.23.0 正式发布说明](https://github.com/vllm-project/vllm-ascend/releases/tag/v0.23.0)：版本组合、硬件范围、已知问题与依赖真源。
- [v0.23.0 文档](https://docs.vllm.ai/projects/ascend/en/v0.23.0/) 与 [官方 Quay 仓库](https://quay.io/repository/ascend/vllm-ascend?tab=tags)：安装说明和镜像下载。镜像允许匿名拉取。
- [CANN 9.1.0 文档](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/910/index/index.html)、[APT 驱动安装](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/910/softwareinst/instg/instg_0108.html)、[YUM 驱动安装](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/910/softwareinst/instg/instg_0107.html)：驱动版本按产品分别为 A2/A3/310P `26.0.RC1`、A5/950 `25.7.RC1`。
- vLLM 与 vLLM Ascend 是 Apache-2.0；Torch 与 torch-npu 使用各自项目的 BSD 风格 LICENSE（GitHub SPDX 返回 `NOASSERTION`）；Triton Ascend 是 MIT；Python 是 PSF-2.0。镜像内 CANN、驱动和固件受华为软件许可/EULA 约束，公开镜像可拉取不等于这些组件改为开源许可。
- 驱动/固件必须从[昇腾官方驱动下载入口](https://www.hiascend.com/developer/download/community/result?module=driver)按精确产品选择。下载可能需要登录、接受 EULA 或厂商/管理员权限；不得把账号、cookie、token 或带签名参数的临时 URL 写入仓库。

## SHA-256 与链接复现结果

2026-09-01 通过匿名 Registry V2 API 对 8 个 tag 做了三层校验：tag 返回的 OCI index 响应字节 SHA-256、index 中 `linux/arm64` manifest digest、manifest 引用的 config digest。三层均可从 Quay 重新下载并复现，脚本不会下载数十 GB 的 layer。

```bash
# 仅检查清单结构；不联网
python3 scripts/verify_ascend_runtime_matrix.py

# 复现 OCI index / ARM64 manifest / config digest
python3 scripts/verify_ascend_runtime_matrix.py --registry

# 同时读取所有官方来源链接
python3 scripts/verify_ascend_runtime_matrix.py --all
```

链接检查只读取公开内容且不发送凭据。华为下载门户不是一个对所有产品都稳定、匿名、不可变的包 URL，因此清单只保存官方选择入口；实际 HDK 包的 SHA-256 必须由管理员在受控资产库登记。

## 已知缺口、失效与冲突

| 类别 | 结论 | 处置 |
|---|---|---|
| 失效链接 | 本次批准矩阵中的 Quay、GitHub、官方文档链接均可访问；未发现失效的批准下载链接 | CI/例行维护继续执行 `--all`；首次失败先复测，连续两次失败再标记失效 |
| 缺失架构 | 正式 image index 只有 Linux ARM64/AMD64；无 Windows、macOS、ppc64le、riscv64；当前 `nightly-main-a5` Ubuntu 还缺 ARM64 | 不自行寻找非官方包；确有需求时向上游提案；nightly 缺口向上游报告 |
| 缺失硬件 | Ascend 910/910 Pro B、Atlas 200I A2（310B）不受支持 | 不标记为社区支持，除非上游改变范围且 HUST 完成验收 |
| 缺失组件 | 310P 不支持 Triton Ascend | 记录为 `null`，不得误填 3.2.2 |
| 固件缺口 | 没有跨产品通用的“最低固件版本”；现有 910B2 证据也没有采集 firmware | 管理员按 SKU 获取对应 HDK 配套表和固件，并补采证据 |
| 溯源缺口 | OCI config 无源码 revision 标签、签名或可验证 provenance/SBOM | commit 只写作 release 引用；推动上游增加 OCI revision 与签名证明 |
| 版本冲突 | 仓库历史指引仍有 `v0.17.0rc1/CANN 8.5.1`，而正式基线已是 `v0.23.0/CANN 9.1.0` | 当前/default 路径统一指向本矩阵；旧组合仅作回滚记录 |
| 310P 冲突 | 上游有 `v0.23.0 + driver 25.5.2` 初始化失败报告 | 使用官方文档的 `26.0.RC1` 线并等待问题关闭 |
| HUST 证据缺口 | 8 个当前组合在上游重建后均未完成新 commit 的实机验收 | 2026-08-19 A2/openEuler/910B2 收据保留为重建前历史证据，但不能证明当前源码；8 项均须重验 |
| source/image 冲突 | 稳定镜像是 v0.23.0；plugin main Docker 默认 v0.27.1；HUST core main 又是继续移动的上游快照 | 三者分别建 profile，禁止互相继承验证状态 |
| nightly 漂移 | Ubuntu 候选观察到 v0.27.1，openEuler ARM64 候选仍是 v0.26.0 | nightly 只做发现清单；任何采用都需固定 digest、核对包版本并重新验收 |

## 组织管理员协调项

1. 按每台机器的精确 Atlas 型号/SKU 从华为官方入口获取配套 Driver/Firmware；驱动和固件属于宿主机 HDK，不应打入派生镜像。
2. 在受限的组织资产库保存包文件、官方 checksum（如有）、本地 SHA-256、获取日期、EULA/工单依据；公开仓库只登记不可泄密的收据，不存包和凭据。
3. 下次 910B2 验收补采 firmware；并对全部 8 个组合使用重建后、可从官方上游根谱系审计的 core/plugin commit 安排真实 NPU 验收。
4. 向上游推动 OCI `revision` 标签、SBOM、签名/provenance，使镜像与 core/plugin commit 可密码学关联。

维护职责与发布门禁见 [Ascend 运行矩阵维护流程](ascend-runtime-matrix-maintenance.md)。
