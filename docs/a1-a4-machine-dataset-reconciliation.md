# A1—A4 机器数据集对账说明

## 对账结论

- 原大矩阵的 **87 列不是 87 个物理数据集**，而是从测试大纲提取的 workload/configuration ID。
- 当前机器资产根目录有 **56 个顶层资产项**，但其中混有数据集、代码仓库、wheel/zip、生成器、重复来源和未完整下载项。
- 按“同一物理数据集家族只占一列”去重后，当前主矩阵列出 **44 个可访问的数据集或请求轨迹家族**。
- 同一数据集可以映射到 A1—A4 的多个测试配置，但不能因此重复成为多个数据集列。

权威列清单为 `config/a1-a4-physical-dataset-registry.csv`；结果填写表为 `docs/a1-a4-metric-dataset-matrix.csv`。

## 不进入物理数据集列的机器资产

| 类别 | 机器资产 | 处理方式 |
|---|---|---|
| 代码/生成器 | `ruler`、`workload-generators` | 冻结代码提交；生成请求集合后，对请求文件单独做 SHA-256，不当作现成数据集 |
| 代码仓库或缓存副本 | `gpqa-github`、`gpqa`、`infinitebench`、`livecodebench`、`structeval-code` | 映射到对应数据家族，不重复计列 |
| 安装包/压缩包 | `bfcl-v4-pypi`、`structeval-788a40c.zip`、`structeval-main.zip` | 作为来源或封装证据保留，不重复计列 |
| 企业资产来源包 | `paio-cloud` | 八个已物化 PAIO 数据文件分别计列，来源包本身不计列 |
| 未完整下载 | `lmsys-chat-1m` | 当前只有说明文件，需授权下载并完成哈希核验后才可入列 |

ToolBench 的旧下载入口曾失效，但已于 2026-08-21 从官方 Google Drive 文件夹的
新文件 ID 完整取得 `data.zip`，通过 ZIP 校验并接纳 G1/G2/G3、test splits、工具
环境和答案数据，因此现已进入物理数据集列。旧的 BFCL/ToolBench 失败下载目录、
partial ZIP 和 0-byte 文件已按项目负责人要求于 2026-08-21 全部清理，不再作为
活动资产或历史证据保留。

## 口径

“数据集列”表示机器上可读取、可冻结并可生成确定请求集合的数据家族。合成 input/output 长度、并发、request rate、prefix 比例、调度策略等属于测试配置；它们写入测试合同，不新增数据集列。到达轨迹（如 BurstGPT）和请求轨迹（如 SyFi）在注册表中明确标注类型，避免与带标准答案的质量数据集混淆。
