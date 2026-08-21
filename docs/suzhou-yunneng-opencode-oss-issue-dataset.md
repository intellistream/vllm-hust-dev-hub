# 苏州云能 OpenCode 开源 Issue 解决生产优化数据集

## 定位

该数据集由苏州云能组织采集并用于生产优化。输入任务来自真实开源项目 Issue，输出由冻结版本 OpenCode 在真实仓库 checkout 中实际生成。`producer=苏州云能`不改变 Issue、代码和许可证的上游归属；不得将其描述为苏州云能原创 Issue 或真实线上流量。

适用范围为 A2 Tool/Agent 与 Reasoning/Code 扩展、A4 Tool/Reasoning 租户扩展以及长程代码 Agent。结果单列，不替代 BFCL/tau2，也不进入 A1—A4 硬门槛。

## 已冻结资产

- asset_id：`SZYN-OPENCODE-SWEBENCH-VERIFIED-500`
- 物理根：`/data/shared_datasets/vllm-hust-evaluation/a1-a4/assets/suzhou-yunneng-opencode-oss-issues/`
- 任务源：`princeton-nlp/SWE-bench_Verified@c104f840cc67f8b6eec6f759ebc8b2693d585d4a`
- 任务源 parquet SHA-256：`a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`
- 任务数：500；12个真实Python开源项目；不抽样，按 `case_key` 排序
- ordered tasks SHA-256：`9b9ee6a71f19bd178ab07d68622478757fc36aadc3c1b9c50f5afe8fad28c0ed`
- hidden oracle hashes SHA-256：`425255e9eb15d7186557213151b36dace33274f335a227ad2913fde14153e386`
- task-pool manifest SHA-256：`84a2ad4e3931d93bd8406d048bcf12c37cc771886812d04fc74f54b8bde7f3fa`
- 统一资产清单版本：`V4.5-A1-A4-ASSETS-20260821.4`
- 统一资产清单 SHA-256：`43c7dd8f96c66c70c3623cf2413d06442d33aa68aef58f2fe9a4b8f762737db6`

OpenCode：

- 官方版本：`v1.18.19`，release commit `2b72179c663cadcb54f54d9f19221b3fb3d11fb6`
- 平台：Linux ARM64
- 官方压缩包 SHA-256：`506f98a1f618551f1f6fc5dcf591f824bef9d6819d40b27928ad7febcb7c363b`
- 二进制 SHA-256：`c34a30f5567f989d9a089cc4a0bf5860d81273fc6644de96671bd5cbe5dd31ec`
- 安装路径：`/data/shared_datasets/vllm-hust-evaluation/a1-a4/tools/opencode/v1.18.19/opencode`

SWE-bench执行工具源码冻结于commit `7a21e05772954cc81471ae19d56f436cecf43c54`，源码归档SHA-256为`69c1b63d3b901ea69a69d40c01f3b9ac1dbe1f8fadbe05885be9ef85542a82f6`。

## 轨迹合同

每次实际执行必须保留有序输入、repo/base commit、OpenCode JSON event stream、session export、工具调用和返回、文件读写、最终patch、测试命令和输出、失败/超时/重试、环境、模型/provider以及全量SHA-256。gold patch和test patch不进入Agent输入，只用于隐藏评估。

OpenCode版本、模型、provider、prompt合同或sandbox变化都产生新的数据集版本。成功、失败、超时和无效patch全部保留，不按结果选择样本。

当前工具和500条任务池已经就绪；批量轨迹采集仍保持inactive，直到明确冻结采集模型/provider和仓库sandbox合同。
