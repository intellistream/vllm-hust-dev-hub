# vLLM-HUST Website 目标基线对比任务交接说明

更新时间：2026-05-07

本文档用于把当前进行中的“website 顶部目标基线对比”任务交接给下一位执行者。不要再从“设计方案”阶段重来，当前需要延续的是已经跑通的官方 baseline 链路，以及尚未闭环的 same-spec current 对照实验。

补充说明：official Ascend goal-baseline 的 canonical home 现已固定在 `vllm-hust-benchmark`。`reference-repos/vllm` 与 `reference-repos/vllm-ascend` 继续作为官方 `v0.11.0` tag/worktree 和历史结果来源，不再作为 baseline spec/runner 的主维护入口。

## 1. 任务背景

需求已经明确，不是做一个泛化的 leaderboard compare 组件，而是建立一条稳定链路，让 website 顶部明确展示：

- 当前 `vllm-hust` 距离官方 Ascend 目标基线还有多远
- 目标基线固定为 `Official Ascend Jan 2026`
- 当前采用的真实基线定义是：
  - `vllm v0.11.0`
  - `vllm-ascend v0.11.0`

最终要形成的是一条正式的“性能对比测试 + 网站展示”链路，而不是一次性的手工截图对比。

## 2. 任务总目标

需要交付的不是单个页面修改，而是一整条端到端链路：

1. 在 `vllm-hust-benchmark` 中维护官方 baseline 的 benchmark spec、环境准备脚本和 runner。
2. 通过 `reference-repos/vllm` / `reference-repos/vllm-ascend` 的 `v0.11.0` worktree 固定官方运行时。
3. 跑出真实官方 baseline benchmark 结果，并导出 website 可消费的 leaderboard artifact。
4. 跑出 same-spec current `vllm-hust` artifact，作为 website compare 的 current 对照项。
5. 在 `vllm-hust-website` 聚合 current artifact 与 official artifact，生成 `goal_progress` compare snapshot。
6. 让 website 顶部优先展示固定目标对比，并据此判断问题来自 compare 口径还是 runtime regression。

## 3. 当前已经完成的工作

### 3.1 website 聚合层已支持固定目标基线

`vllm-hust-website` 已支持聚合固定目标基线并生成 `goal_progress`：

- 仅识别满足以下条件的 baseline 条目：
  - `engine == vllm`
  - `engine_version` 以 `0.11.0` 开头
  - `metadata.github_repository == vllm-project/vllm-ascend`
- 聚合时已经加入 model name normalization，用于配对：
  - current 可能是 `Qwen2.5-14B-Instruct`
  - baseline 可能是 `Qwen/Qwen2.5-14B-Instruct`
- 前端 hero 已优先读取 `goal_progress`，有配对时直接展示固定目标对比

对应文件：

- `/root/workspace/vllm-hust-website/scripts/aggregate_results.py`
- `/root/workspace/vllm-hust-website/tests/test_aggregate_results.py`
- `/root/workspace/vllm-hust-website/assets/leaderboard.js`
- `/root/workspace/vllm-hust-website/assets/leaderboard.css`

### 3.2 official baseline runner 与环境脚本已迁到 `vllm-hust-benchmark`

当前在 `vllm-hust-benchmark` 中维护：

- `scripts/prepare-official-ascend-baseline-env.sh`
- `scripts/run-official-ascend-goal-baseline.sh`
- `docs/official-baselines/official-ascend-jan-2026-v0110-random-online-qwen25-14b-910b3.json`
- `docs/official-baselines/official-ascend-constraints.stub.json`
- `README.md`

当前 runner/prepare 流程已具备以下关键行为：

- 使用 `/tmp` 这类 neutral cwd 启动 Python 命令，避免 editable import 串到 workspace checkout
- 通过 `/tmp/vllm-v0110` 与 `/tmp/vllm-ascend-v0110` worktree 绑定官方 `v0.11.0` 运行时
- random dataset 参数会从 `input_len` / `output_len` 显式转换为 `--random-input-len` / `--random-output-len`
- server 默认补上 `--enforce-eager`，绕过 ACL graph `weak_ref_tensor` 启动失败
- runner 优先解析本机已缓存的 Hugging Face snapshot；如需显式指定本地模型目录，可使用 `OFFICIAL_MODEL_PATH=/abs/model/path`
- `prepare-official-ascend-baseline-env.sh` 会在 benchmark 启动前执行准入清理，主动清理残留 `api_server` / `bench serve` / `EngineCore_DP0` 进程以及占用 benchmark 端口的残留句柄

### 3.3 official baseline 已真实跑通，artifact 已经产出

已确认存在的官方 baseline 结果包括：

- 首次真实跑通后保留在 `reference-repos/vllm-ascend` 下的历史结果：
  - `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/raw_benchmark_result.json`
  - `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/submission/run_leaderboard.json`
- 使用 benchmark 仓内 canonical runner 与 fresh env 再次验证得到的结果目录：
  - `/workspace/vllm-hust-benchmark/.benchmarks/official-ascend-goal-baseline-fresh-20260507T-run4/raw_benchmark_result.json`
  - `/workspace/vllm-hust-benchmark/.benchmarks/official-ascend-goal-baseline-fresh-20260507T-run4/submission/run_leaderboard.json`

已固定的 baseline 元信息口径：

- engine: `vllm`
- engine_version: `0.11.0`
- github_repository: `vllm-project/vllm-ascend`
- github_ref: `v0.11.0`

### 3.4 官方环境已经准备成仓内可复用流程

官方 baseline 的准备不再依赖临时手工命令，当前已有仓内脚本：

- `prepare-official-ascend-baseline-env.sh`：创建/修复官方专用环境，并在 benchmark 启动前做准入清理
- `run-official-ascend-goal-baseline.sh`：在固定 worktree 与固定 spec 下启动 server、执行 benchmark、导出 artifact

推荐官方环境路径：

- `/root/miniconda3/envs/vllm-ascend-official-v0110`

### 3.5 已验证的关键事实

- official baseline 必须从 neutral cwd 启动，否则可能误导入 workspace checkout
- official `v0.11.0` random dataset CLI 需要 `--random-input-len/--random-output-len`
- official baseline server 需要 `--enforce-eager`
- current `vllm 0.20.1` 的 `api_server` 不再接受 `--disable-log-requests`
- 聚合层的 goal-pair 配对已经通过 model name normalization 修好
- website 的相关聚合测试已通过

## 4. 当前最关键的未完成工作

### 4.1 same-spec current artifact 仍然缺失

当前最大的未决问题不是 official baseline，而是 current `vllm-hust` 的 same-spec 对照实验还没有成功落地 artifact。

已确认的 current 环境与差异：

- conda env: `/home/shuhao/miniconda3/envs/vllm-hust-dev`
- `vllm` version: `0.20.1`
- current `api_server` 不再接受 `--disable-log-requests`
- 同口径 current server 曾成功通过健康检查，但 client 侧 benchmark 结果没有稳定落盘

因此现在还不能判断：

- 是 current runtime regression
- 还是 `vllm bench serve` 在 current `0.20.1` 路径下存在 client 侧异常
- 还是 API 兼容性导致 benchmark 没成功保存结果

### 4.2 website 当前的 current entry 仍不是严格同 spec

当前 website 数据中的 `vllm-hust` entry 不是严格同 spec 的 current artifact，已知至少存在这些偏差：

- model name 口径可能不同
- workload scope 中可能混入 `concurrent_requests`、backend、serving flags 等差异
- metadata provenance 仍不完整

因此在 same-spec current artifact 没跑出来前，不能把“current 明显慢于 baseline”直接定性为 runtime regression。

### 4.3 `Hard Constraints` 的语义修正还没闭环

当前还需要补的 UI 语义修正是：

- `Hard Constraints` 只用于展示 `vllm-hust`
- baseline `vLLM 0.11.0` 不应被渲染成 “fail to meet hard constraints”

这项工作应放在 same-spec current artifact 之后，而不是之前。

## 5. 当前涉及的仓库与职责边界

### 5.1 `vllm-hust-website`

职责：

- 消费 artifact
- 聚合 current 与 baseline 数据
- 在前端顶部展示目标差距

不应该承担的职责：

- 不直接跑官方 baseline benchmark
- 不管理官方 baseline 环境安装

### 5.2 `vllm-hust-benchmark`

职责：

- 作为 official baseline spec / prepare / runner 的 canonical home
- 负责调用 benchmark 与 artifact export
- 作为 website 目标对比的标准执行入口

### 5.3 `reference-repos/vllm` 与 `reference-repos/vllm-ascend`

职责：

- 提供官方 `v0.11.0` 代码来源
- 供 baseline runner 拉 worktree 与固定官方运行时
- 保留历史结果与 upstream 对照

不应继续作为自定义 benchmark runner/spec 的提交落点。

### 5.4 `vllm-hust` 与 `vllm-ascend-hust`

职责：

- 当 same-spec current artifact 仍显著慢于 baseline 时，承接 runtime regression 排查
- 重点检查 serving flags、scheduler、Ascend plugin 差异和请求路径兼容性

## 6. 当前已准备好的环境与路径

### 6.1 官方 baseline conda 环境

推荐环境路径：

- `/root/miniconda3/envs/vllm-ascend-official-v0110`

### 6.2 官方代码 worktree

当前已经准备好的官方 worktree：

- `/tmp/vllm-v0110`
- `/tmp/vllm-ascend-v0110`

### 6.3 current 对照环境

当前 same-spec current 对照实验使用的环境：

- `/home/shuhao/miniconda3/envs/vllm-hust-dev`

## 7. 建议的接手动作顺序

### 阶段 A：如需复核官方 baseline，使用 benchmark 仓内流程

```bash
export ENV_PREFIX=/root/miniconda3/envs/vllm-ascend-official-v0110
bash /root/workspace/vllm-hust-benchmark/scripts/prepare-official-ascend-baseline-env.sh

export GOAL_BASELINE_ENV_PREFIX=/root/miniconda3/envs/vllm-ascend-official-v0110
bash /root/workspace/vllm-hust-benchmark/scripts/run-official-ascend-goal-baseline.sh \
  /root/workspace/vllm-hust-benchmark/docs/official-baselines/official-ascend-jan-2026-v0110-random-online-qwen25-14b-910b3.json
```

这一步主要用于验证官方环境、runner 和 artifact export 仍然可用，不是当前最高优先级。

### 阶段 B：优先把 same-spec current artifact 跑出来

这是当前最高优先级。不要先改 website UI 语义，也不要先重构 compare 逻辑。

必须先回答：

- 用与 official baseline 完全相同的 workload spec 跑 current `vllm-hust`，结果到底是多少？

### 阶段 C：一旦 current artifact 成功，立刻导出 leaderboard artifact

然后与 official artifact 直接对比：

- throughput
- TTFT
- TBT/TPOT

### 阶段 D：最后再决定后续方向

分叉判断：

1. 如果 same-spec current 接近 baseline：修 website compare 口径或刷新 current artifact 数据。
2. 如果 same-spec current 仍显著慢：转入 `vllm-hust` / `vllm-ascend-hust` 做 runtime regression 排查。
3. 无论哪种情况，之后都应补上 `Hard Constraints` 只展示 `vllm-hust` 的 UI 语义修正。

## 8. 关键路径与文件

### website

- `/root/workspace/vllm-hust-website/scripts/aggregate_results.py`
- `/root/workspace/vllm-hust-website/tests/test_aggregate_results.py`
- `/root/workspace/vllm-hust-website/assets/leaderboard.js`
- `/root/workspace/vllm-hust-website/assets/leaderboard.css`

### official baseline

- `/root/workspace/vllm-hust-benchmark/scripts/prepare-official-ascend-baseline-env.sh`
- `/root/workspace/vllm-hust-benchmark/scripts/run-official-ascend-goal-baseline.sh`
- `/root/workspace/vllm-hust-benchmark/docs/official-baselines/official-ascend-jan-2026-v0110-random-online-qwen25-14b-910b3.json`
- `/root/workspace/vllm-hust-benchmark/docs/official-baselines/official-ascend-constraints.stub.json`
- `/root/workspace/vllm-hust-benchmark/README.md`

### 官方结果与运行时路径

- `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/raw_benchmark_result.json`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/submission/run_leaderboard.json`
- `/workspace/vllm-hust-benchmark/.benchmarks/official-ascend-goal-baseline-fresh-20260507T-run4/raw_benchmark_result.json`
- `/workspace/vllm-hust-benchmark/.benchmarks/official-ascend-goal-baseline-fresh-20260507T-run4/submission/run_leaderboard.json`
- `/tmp/vllm-v0110`
- `/tmp/vllm-ascend-v0110`

### handoff 文档

- `/root/workspace/vllm-hust-dev-hub/docs/website-goal-baseline-handoff-20260506.md`

## 9. 风险与注意事项

### 9.1 当前固定识别的是 `v0.11.0`

如果后续产品要把官方目标版本改成别的时间点，需要同步更新：

- baseline spec 中的 `engine_version`
- `github_ref`
- `git_commit`
- website 侧目标 baseline 识别逻辑

### 9.2 当前 constraints 不是实测值

`official-ascend-constraints.stub.json` 只用于打通 artifact 导出链路，不代表 hard constraints 已完成基线评估。

### 9.3 runner 对本地模型缓存有依赖

离线环境下，runner 依赖本机 Hugging Face 缓存；如缓存不可用，需要显式设置 `OFFICIAL_MODEL_PATH`。

### 9.4 当前只覆盖一个重点 scope

当前任务先聚焦一条官方目标基线。如果要扩展到多模型、多硬件、多 workload，需要额外补充 spec、artifact 和 compare 口径。

## 10. 当前改动文件清单

### 已修改的 website 文件

- `/root/workspace/vllm-hust-website/scripts/aggregate_results.py`
- `/root/workspace/vllm-hust-website/assets/leaderboard.js`
- `/root/workspace/vllm-hust-website/assets/leaderboard.css`
- `/root/workspace/vllm-hust-website/tests/test_aggregate_results.py`

### 已新增或修改的 official baseline 文件

- `/root/workspace/vllm-hust-benchmark/scripts/prepare-official-ascend-baseline-env.sh`
- `/root/workspace/vllm-hust-benchmark/scripts/run-official-ascend-goal-baseline.sh`
- `/root/workspace/vllm-hust-benchmark/docs/official-baselines/official-ascend-jan-2026-v0110-random-online-qwen25-14b-910b3.json`
- `/root/workspace/vllm-hust-benchmark/docs/official-baselines/official-ascend-constraints.stub.json`
- `/root/workspace/vllm-hust-benchmark/README.md`

### 本次 handoff 文档

- `/root/workspace/vllm-hust-dev-hub/docs/website-goal-baseline-handoff-20260506.md`

## 11. 推荐给接手 team 的第一天执行清单

1. 阅读本文档和上述改动文件。
2. 先确认 benchmark 仓内 official baseline prepare / runner 流程仍可执行。
3. 重点重跑 same-spec current benchmark，并完整保留 stdout/stderr。
4. 一旦拿到 current `raw_benchmark_result.json`，立刻导出 current leaderboard artifact。
5. 将 current artifact 与 official artifact 一起聚合进 website 数据。
6. 本地启动 website，确认顶部 hero 是否显示目标差距。
7. 最后再决定是修 compare 口径还是查 runtime regression。

## 12. review 重点

review 这条链路时，优先看下面几件事：

1. official baseline 的 canonical home 是否始终保持在 `vllm-hust-benchmark`。
2. runner 是否仍然绑定 `reference-repos/vllm` / `reference-repos/vllm-ascend` 的 `v0.11.0` worktree，而不是误用 workspace checkout。
3. benchmark 启动前是否仍把残留进程清理作为准入条件。
4. website compare 是否始终以 same-spec current artifact 对 official artifact 做配对，而不是拿历史杂糅数据直接比较。

## 13. 一句话交接摘要

official baseline 链路已经跑通，且 canonical home 已迁到 `vllm-hust-benchmark`；下一位执行者不需要重新设计方案，而是要优先拿到 same-spec current artifact，再用它和官方 `v0.11.0` baseline 做对比，完成 website 顶部目标差距展示的数据闭环。
