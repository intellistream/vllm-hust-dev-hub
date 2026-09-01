# Ascend 运行矩阵维护流程

## 责任边界

- **矩阵维护者**：跟踪 vLLM Ascend release、更新 JSON、运行公开来源校验、提交 PR。
- **NPU 验证者**：在目标硬件上采集 Driver/Firmware/CANN/Python/Python 包、OCI identity、core/plugin commit 和最小启动证据。
- **组织管理员**：按精确产品从华为官方渠道取得 HDK，管理 EULA/权限和受限资产库。公开仓库不得存驱动包、固件包或访问凭据。
- **评审者**：核对来源级别、版本一致性、digest、许可证、访问限制和验证状态，避免把“镜像存在”误写为“组织验证”。

当前源码政策：`vllm-hust` 与 `vllm-ascend-hust` 是从官方上游直接重建的组织仓库。官方上游分别为 `vllm-project/vllm` 与 `vllm-project/vllm-ascend`；重建前 commit 和旧 fork-only 历史不得作为当前源码或当前验证依据。

## 新版本更新步骤

1. 只从 vLLM Ascend GitHub release、版本化官方文档、release commit 的 Dockerfile、Quay Registry V2 API 和华为 Ascend 官方文档取数。
2. 枚举正式版的 A2/A3/A5/310P 与 Ubuntu/openEuler tag。排除 main、nightly、dev、模型专用和镜像站独有 tag。
3. 对每个 tag 读取 OCI index，保存 index digest；从 index 选择 `linux/arm64`，保存 manifest digest和 config digest。禁止仅保存可变 tag。
4. 从 release note 与实际 config/Dockerfile交叉核对 CANN、Torch、torch-npu、Triton Ascend、Python、vLLM、vLLM Ascend。冲突时保持 `not_verified` 并在 `known_conflicts` 记录，不能猜测。
5. 解析上游 core/plugin release tag 的完整 40 位 commit。没有 OCI revision/provenance 时，明确标注为 release 引用 commit，而非镜像构建证明。
6. 从华为对应 CANN 版本的 Driver 安装页按产品记录最低驱动线；固件只引用同产品 HDK 配套表，不跨产品推断统一版本。
7. 更新许可证和访问限制。任何需要登录、EULA 或授权的资源只保存官方入口，不保存 cookie、token、账号、临时签名 URL 或非官方网盘副本。
8. 运行校验并保存输出到 PR 描述：

   ```bash
   python3 scripts/verify_ascend_runtime_matrix.py
   python3 scripts/verify_ascend_runtime_matrix.py --registry
   python3 scripts/verify_ascend_runtime_matrix.py --links
   pytest -q tests/test_ascend_runtime_matrix.py
   ```

9. 先合并清单与文档；只有真实 NPU 证据齐全后，才把对应 HUST 状态从 `not_verified` 改为 `community_verified`。
10. 仓库重建、重新导入或更换源码根时，把所有依赖旧 commit 的 `community_verified` 降回 `not_verified`。旧证据只保留为历史收据，直到使用重建后可达 commit 重新运行。

## 社区验证最小证据

每个 OS/架构/NPU 组合单独验收。证据至少包括：

- `docker image inspect` 的 RepoDigest、Architecture、OS 和 image ID；
- `npu-smi info`、`cat /usr/local/Ascend/driver/version.info`（实际路径存在时）及固件查询输出；
- CANN version、Python `--version`、`pip freeze` 中 Torch/torch-npu/Triton/vLLM/vLLM Ascend；
- vLLM-HUST core/plugin 的完整 commit，工作树是否干净，以及 overlay 安装命令；
- 两个 commit 在重建后组织仓库中的可达性，以及其对应官方上游根；不得用已经因重建而不可达的旧 fork commit；
- 单 NPU 最小模型加载、一次确定性请求、正常退出、退出后无残留 NPU 进程；
- 原始文本证据的 `SHA256SUMS`。不得用截图替代可机器读取的关键版本输出。

上游 release、CI 或公开镜像可把 `upstream_verification` 标为 `official_verified`；只有本组织真实硬件证据才能改变 `vllm_hust_verification`。

## 失效与回滚

- tag digest 变化是供应链事件：立即停止用 tag 拉取，保留旧 digest，不自动接受新 digest，开启上游核查。
- 链接首次失败记为维护告警；不同网络和时间第二次复测仍失败后才列为失效。找到的新地址必须仍属于同一官方域名和同一版本。
- 已发布 digest 被 registry 删除时，记录删除时间和最后成功证据。未经管理员批准，不用镜像站 digest 替换官方 digest。
- 新 release 未完成 HUST 验收时，旧的、已经验证的 immutable digest 继续作为回滚基线；不得用 nightly 顶替。

## 建议周期

- 每周：运行本地结构校验和 Registry digest 校验。
- 每月：运行全部链接校验，检查上游 release/FAQ/已知问题和 HDK 配套页。
- 每个正式 release：执行完整更新步骤并至少完成组织主力机型的真实 NPU 验收。
- 每次 Driver/Firmware 变更：重新验证容器初始化、最小推理与退出清理，并更新受限资产收据。
