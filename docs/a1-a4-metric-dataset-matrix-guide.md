# Metric × 数据集大矩阵使用说明

大矩阵文件：`docs/a1-a4-metric-dataset-matrix.csv`。

结构固定为：

- 纵向：档位、Metric、计算公式、单位、适用范围；
- 横向：机器上已物化且可读取的 44 个去重数据集/请求轨迹家族；
- 单元格：填写该数据集的结果，推荐格式 `B0=值；B1=值；B1/B0=值`；
- 不适用填 `N/A`，资产阻塞填具体状态，尚未测试留空；
- 最上面的 `REQUIRED` 行是第三方必须交付的结果；后面的 `ADDITIONAL` 行仅作附加分析。

当前固定为 19 个 `REQUIRED` 和 10 个 `ADDITIONAL`。`REQUIRED` 中带适用
条件的指标（例如正确率、静默截断率）在不适用的数据集上填 `N/A` 并说明原因，
不能填 0；适用但缺失时，对应结论为 `CANNOT_DETERMINE`。

列名权威来源为 `config/a1-a4-physical-dataset-registry.csv`。同一数据集被多个
workload/configuration 引用时只占一列；合成长度、并发、request rate、prefix
比例、调度方式等属于测试配置，不占数据集列。56 个顶层机器资产为何最终对应
44 列，以及被排除或合并的资产，见
`docs/a1-a4-machine-dataset-reconciliation.md`。

最核心公式：

| Metric | 公式 |
|---|---|
| 请求吞吐 | `N_ok / T` |
| 输入吞吐 | `Σ input_tokens / T` |
| 输出吞吐 | `Σ output_tokens / T` |
| 总吞吐 | `Σ(input_tokens + output_tokens) / T` |
| TTFT | `t_first - t_send` |
| TPOT | `(t_last - t_first) / (output_tokens - 1)` |
| E2E | `t_end - t_send` |
| 成功率 | `N_ok / N_plan` |
| 正确率 | `N_correct / N_plan`，或使用冻结的官方 scorer |
| B1/B0 吞吐比 | `median(Q_B1) / median(Q_B0)` |
| 吞吐提升率 | `(B1/B0 - 1) × 100%` |
| 时延改善率 | `(1 - L_B1/L_B0) × 100%` |
| 极限百万 token 成本 | `H × 10^6 / (3600 × Q_raw)` |
| SLO 百万 token 成本 | `H × 10^6 / (3600 × Q_slo)` |
| 报价（加价率） | `(C_slo/φ) × (1+c_cloud) × (1+r_markup)` |
| 报价（会计毛利率） | `(C_slo/φ) × (1+c_cloud) / (1-m_gross)` |

同一张表中不要混淆 input、output 和 total token 吞吐。报价默认使用满足 SLO 的
`C_slo`；`C_raw` 只表示极限跑满成本下界。加价率报价是主交付口径；会计毛利率
报价是备选口径，只有合同明确选择它时才升级为 `REQUIRED`。
