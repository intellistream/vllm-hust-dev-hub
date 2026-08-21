# Metric × 数据集大矩阵使用说明

大矩阵文件：`docs/a1-a4-metric-dataset-matrix.csv`。

结构固定为：

- 纵向：档位、Metric、计算公式、单位、适用范围；
- 横向：A1—A4 中每一个数据集或 workload；
- 单元格：填写该数据集的结果，推荐格式 `B0=值；B1=值；B1/B0=值`；
- 不适用填 `N/A`，资产阻塞填具体状态，尚未测试留空；
- `必测` 行进入正式验收，`补充` 行只用于诊断。

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

同一张表中不要混淆 input、output 和 total token 吞吐。报价默认使用满足 SLO 的 `C_slo`；`C_raw` 只表示极限跑满成本下界。
