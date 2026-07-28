# 真遗漏 vs 已知约束

本 checklist 只列"真遗漏"——脚本或工作流里缺少但应该有的功能。`agent.md` 已明示的约束(如 910B2 默认、禁用 enforce-eager、目录边界)不算遗漏,属于"已知约束"。

优先级定义:

- P0 = 阻塞当前数据流
- P1 = 影响数据可信度或可维护性
- P2 = 改进项

# 12 条遗漏

按 P0→P1→P2 排序。

| # | 遗漏描述 | 影响范围 | 优先级 | 修复位置 |
|---|---------|---------|--------|---------|
| 1 | PR #99 验证阻塞:当前有 118 行验证错误,处于 BLOCKED 状态 | 阻塞最新 backfill 批次合入,影响 #89 进度 | P0 | `scripts/backfill_single_gpu.py`(submission 生成路径)+ `scripts/validate_public_leaderboard_snapshots.py` |
| 2 | prefix-repetition-online 启动故障(issue #97):PR #80 的 prefix-repetition-online 启动故障未解,曾用 monkeypatch 绕过 | 该 workload 数据缺口持续存在 | P0 | `scripts/backfill_single_gpu.py::run_cell` 启动健康检查路径 |
| 8 | `backfill_single_gpu.md` 文档与代码不一致:`backfill_single_gpu.md` 提到 `SAME_SPEC_GPU_MEMORY_UTILIZATION` 和 `SAME_SPEC_MAX_MODEL_LEN` 两个环境变量,但 `backfill_single_gpu.py` 代码中不存在(实际是模块常量 `DEFAULT_GPU_MEMORY_UTILIZATION`/`DEFAULT_MAX_MODEL_LEN`);且文档把 `MAX_MODEL_LEN` 默认值写为 30720,实际代码常量是 32768 | 误导操作者试图通过环境变量覆盖,实际不生效;30720 已被 `validate_public_leaderboard_snapshots.py` 标记为 `RETIRED_PUBLIC_MAX_MODEL_LEN` | P0 | `vllm-hust-benchmark/scripts/backfill_single_gpu.md`(修正文档) |
| 3 | `backfill_single_gpu.py` 单文件 3761 行:8 个子命令耦合(plugin 解析、NPU 选择、server/client、validate、aggregate、push、restore) | 任何改动风险高,#80 曾因 monkeypatch 源码被 flag | P1 | 拆分为 `backfill/` 包(run/plan/aggregate/validate/push 分文件) |
| 4 | plugin/engine canonical 双向校验缺失:plugin commit canonical 规则依赖 earliest-submitted entry 正确,但 a46abb7 事件证明 earliest entry 本身可能 engine_version 错误(`0.18.0.post1` vs `git describe`) | 若 earliest entry 的 plugin/engine 元数据本身错,canonical 被污染,后续所有同 commit entry 被迫对齐到错误值 | P1 | `scripts/backfill_single_gpu.py::assert_plugin_commit_consistent` 增加 engine_version 一致性校验 |
| 5 | 黑名单 ledger 扩充滞后:`docs/HISTORICAL_PR_BENCHMARK_BLACKLIST.md` 仅 1 条黑名单(`bf2984e34a`),但 #89 需 backfill 30 个已合并 PR | 不安全 commit 可能未被识别就进入 public snapshot | P1 | `docs/leaderboard-exclusions.json` + `docs/HISTORICAL_PR_BENCHMARK_BLACKLIST.md` 需随 #89 进度同步扩充 |
| 6 | suspect 目标清理未完成:`archive/suspect/` 有 4 个 suspect 目标(7a63-main、7fa0e3ed4b、main-2206-instructcoder、single-card-high-ttft-outliers),`docs/suspect-historical-targets.md` 显示部分尚未清理 | 趋势图存在 outlier,compare cards 数据不可信 | P1 | `scripts/archive_superseded_coexistence.py` + issue #105 全局清理任务 |
| 9 | 脚本 21 `run_latest_benchmark.sh` 废弃建议:与 `backfill_single_gpu.py`(脚本 9)功能重叠,且硬编码路径(`/root/vllm/...`)与版本(`0.23.1.post1`),绕过 same-spec resolve/export 流程,直接调 `vllm.entrypoints.cli.main bench` | 新成员误用会产出不符合 leaderboard contract 的数据 | P1 | `vllm-hust-benchmark/scripts/run_latest_benchmark.sh`(废弃或重写为脚本 6/9 的薄包装) |
| 10 | 公共 bash 函数抽库建议:`cleanup_managed_server`/`slugify`/`collect_specs`/`json2args`/`probe_server_ready`/`wait_for_server`/`ensure_runtime_dataset_available` 等函数在 `run-current-ascend-same-spec.sh`、`run-official-ascend-goal-baseline.sh`、`prepare-official-ascend-baseline-env.sh` 等脚本中各自重新定义;`json2args` 还有 Python 实现(脚本 1)与 jq 实现(脚本 7)两种,行为可能漂移 | bug 修一处不修另一处,行为不一致 | P1 | 抽到 `scripts/lib/common.sh` sourced 引入;`json2args` 统一为一种实现 |
| 7 | `data_source` marker 强制注入缺失:historical-PR-backfill 的 `data_source` marker 仅靠防御测试保障(`AGGREGATE_CONTRACT.md` §1),手动入库或第三方工具生成的 entry 会缺失 marker 被 website 静默 reject | 跨 PR 对比数据可能静默丢失(实测曾 190 entry 被跳过) | P2 | `src/vllm_hust_benchmark/submission_artifacts.py` 在写入时强制注入 marker,而非仅靠 driver |
| 11 | 参数命名统一建议:25 个脚本里有 7 种 Python 解释器/env 命名、4 种模型路径命名、4 种端口默认值(同机混跑冲突)、4 种 submitter 来源、6 种 repo 路径命名 | 新成员上手成本高,易混淆 | P2 | 统一为 `<DOMAIN>_ENV_PREFIX` + 派生 `<DOMAIN>_RUNTIME_PYTHON` 模式;详见 [07-params-cheatsheet.md](07-params-cheatsheet.md) 的配置一致性对照表 |
| 12 | `backfill_single_gpu.py validate` 子命令缺参数:`validate` 子命令无任何参数(无 `--strict`、`--fix` 等),与 `validate_public_leaderboard_snapshots.py`、`validate_trend_entries.py` 校验范围不重叠 | 缺统一校验入口,需手工调多个校验脚本 | P2 | `vllm-hust-benchmark/scripts/backfill_single_gpu.py` 的 `cmd_validate` 函数 |

# 未发现明显遗漏的领域

- `workload_config_contract.py` 的 `explicit-effective/v1` 校验链完整
- `integration.py` 的 superseded 共存检测有对应测试 `test_integration_aggregation_gate.py`
- perfgate 与 official-baseline 目录边界在 `agent.md` 已明示约束(属已知约束,非遗漏)
