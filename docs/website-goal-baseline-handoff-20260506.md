# vLLM-HUST Website 目标基线对比任务交接说明

更新时间：2026-05-06
本文档用于把当前进行中的“website 顶部目标基线对比”任务交接给下一位执行者。当前代码改动已经分散在多个仓库，且官方 baseline 已经真实跑通一次；接手时不要再从“设计方案”阶段重来，而是直接从已落地的数据链路和未完成的同口径复现实验继续。

## 1. 任务目标
目标不是做一个泛化的 leaderboard 对比组件，而是建立一条稳定链路，让 website 顶部明确展示：

- 当前 `vllm-hust` 距离官方 Ascend 目标基线还有多远
- 目标基线固定为 `Official Ascend Jan 2026`
- 当前采用的真实基线定义是：
  - `vllm v0.11.0`
  - `vllm-ascend v0.11.0`
这条链路包括：

1. 在 `reference-repos/vllm-ascend` 中维护 baseline spec 和 runner
2. 跑出真实官方 baseline benchmark 结果
3. 导出 website 可消费的 leaderboard artifact
4. 在 `vllm-hust-website` 中聚合成 compare snapshot
5. 在 website 顶部优先展示这条固定目标对比
6. 后续用同口径 current artifact 去判断是 website compare 口径问题还是 runtime regression
## 2. 已完成事项

### 2.1 official baseline runner 已落地

仓库：`reference-repos/vllm-ascend`

新增文件：

- `benchmarks/scripts/run-vllm-hust-goal-baseline.sh`
- `benchmarks/tests/vllm-hust-goal-baseline.json`
- `benchmarks/tests/vllm-hust-goal-constraints.stub.json`

README 也已补充用法说明：

- `benchmarks/README.md`

关键实现点：

- runner 默认从 `/tmp` 这样的 neutral cwd 启动 Python 命令，避免错误导入 workspace checkout
- official `v0.11.0` random dataset CLI 不兼容 `--input-len/--output-len`，runner 已自动转成 `--random-input-len/--random-output-len`
- official baseline server 需要 `--enforce-eager` 才能绕过 ACL graph `weak_ref_tensor` 启动失败
### 2.2 official baseline 已真实跑通并导出 artifact

已生成结果目录：

- `reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/raw_benchmark_result.json`
- `reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/submission/run_leaderboard.json`

已验证的 baseline 指标：

- throughput: `205.43238789737052 tok/s`
- TTFT: `281.0340084585497 ms`
- TBT/TPOT: `78.65327996609436 ms`
- completed requests: `178`
- duration: `216.8499351828359 s`

artifact 元信息：

- engine: `vllm`
- engine_version: `0.11.0`
- model: `Qwen/Qwen2.5-14B-Instruct`
- github_repository: `vllm-project/vllm-ascend`
- git_commit: `2f1aed98ccdb0fcbe1ff4fd0abab225bfd8d0367`
### 2.3 website 聚合层已支持目标基线

仓库：`vllm-hust-website`

已修改文件：

- `scripts/aggregate_results.py`
- `tests/test_aggregate_results.py`

主要行为：

- 聚合层现在会生成 `goal_progress`
- 目标 baseline 只认官方条目：
  - `engine == vllm`
  - `engine_version` 以 `0.11.0` 开头
  - `metadata.github_repository == vllm-project/vllm-ascend`
- 为了让 current 和 baseline 正确配对，聚合时已经加入 model name normalization：
  - current 可能是 `Qwen2.5-14B-Instruct`
  - baseline 是 `Qwen/Qwen2.5-14B-Instruct`

已跑通测试：

```bash
cd /root/workspace/vllm-hust-website
conda run -p /home/shuhao/miniconda3/envs/vllm-hust-dev \
  python -m pytest tests/test_aggregate_results.py -q
```

结果：`5 passed`
### 2.4 website hero 和 hard constraints UI 已调整

已修改文件：

- `assets/leaderboard.js`
- `assets/leaderboard.css`

当前行为：

- overview hero 优先读取 `goal_progress`
- 若有 current/baseline pair，则顶部展示固定目标对比
- hard constraints 区域已做摘要式折叠展示，失败 scope 前置

注意：用户后续提出了一个新的语义要求，尚未在代码中确认完成：

- `Hard Constraints` 应该只用于展示 `vllm-hust`
- baseline `vLLM 0.11.0` 不应该被渲染成 “fail to meet hard constraints”

这项语义修正仍然待处理。
## 3. 当前最关键的未完成事项

### 3.1 还缺一条 same-spec current artifact

目前最大的未决问题不是 official baseline，而是 current `vllm-hust` 的对照实验还没有成功落地 artifact。

已确认当前环境：

- conda env: `/home/shuhao/miniconda3/envs/vllm-hust-dev`
- `vllm` version: `0.20.1`
- `vllm` import path: `/home/shuhao/miniconda3/envs/vllm-hust-dev/lib/python3.11/site-packages/vllm/__init__.py`
- benchmark package path: `/workspace/vllm-hust-benchmark/src/vllm_hust_benchmark/__init__.py`
- `vllm-hust` repo commit: `383b3c7acb08654da445c0048fc3f3eed9c4bb19`
- branch: `main`

已确认的 current server 启动差异：

- current `vllm 0.20.1` 的 `api_server` 不再接受 `--disable-log-requests`
- 同口径复现时必须删掉该参数

已成功启动的 current server 口径：

```bash
cd /tmp
ASCEND_RT_VISIBLE_DEVICES=1 \
conda run -p /home/shuhao/miniconda3/envs/vllm-hust-dev \
  python -m vllm.entrypoints.openai.api_server \
  --tensor-parallel-size 1 \
  --enforce-eager \
  --trust-remote-code \
  --disable-log-stats \
  --host 0.0.0.0 \
  --port 8001 \
  --model Qwen/Qwen2.5-14B-Instruct
```

服务器健康检查曾成功返回：

- `curl http://127.0.0.1:8001/health` -> `200`
### 3.2 same-spec current benchmark 目前处于异常状态

尝试的 client 命令：

```bash
RESULT_DIR=/tmp/vllm-hust-same-spec-current
rm -rf "$RESULT_DIR"
mkdir -p "$RESULT_DIR"
cd /tmp
conda run -p /home/shuhao/miniconda3/envs/vllm-hust-dev \
  vllm bench serve \
  --save-result \
  --result-dir "$RESULT_DIR" \
  --result-filename raw_benchmark_result.json \
  --backend vllm \
  --endpoint /v1/completions \
  --dataset-name random \
  --num-prompts 200 \
  --random-input-len 1024 \
  --random-output-len 256 \
  --request-rate 1 \
  --host 127.0.0.1 \
  --port 8001 \
  --model Qwen/Qwen2.5-14B-Instruct
```

异常现象：

- benchmark client 进程曾持续运行，但 `RESULT_DIR` 一直为空
- 后续等待进程结束后，`raw_benchmark_result.json` 仍未落盘
- 当前没有拿到明确的 stderr/root-cause 日志

因此现在还不能判断：

- 是 current runtime regression
- 还是 `vllm bench serve` 在 current `0.20.1` 路径下出现 client 侧异常
- 还是 API 兼容性导致 benchmark 没成功保存结果
### 3.3 website compare 口径问题尚未被排除

当前 website 数据中的那条 `vllm-hust` entry 并不是严格同 spec 的 current artifact。

已知现有 website current entry 与 baseline 不完全同口径，至少包括：

- current entry 使用 bare model name
- workload scope 中可能混入 `concurrent_requests`、backend、serving flags 等差异
- metadata provenance 不完整

所以在 same-spec current artifact 没跑出来前，不能把“current 明显慢于 baseline”直接定性为 runtime regression。
## 4. 接手后的优先级

### 优先级 1：把 same-spec current artifact 跑出来

这是最高优先级。不要先去改网站 UI 语义，不要先重构 compare 逻辑。

必须先回答这件事：

- 用与 official baseline 完全相同的 workload spec 跑 current `vllm-hust`，结果到底是多少？

如果 current 结果恢复接近 baseline：

- 说明更可能是 website compare scope 过粗或现有 current website 数据不是同口径

如果 current 结果仍然显著慢：

- 才进入 runtime regression 排查
### 优先级 2：若 current artifact 成功，立即导出 leaderboard artifact

导出 CLI 已确认可用：

```bash
conda run -p /home/shuhao/miniconda3/envs/vllm-hust-dev \
  python -m vllm_hust_benchmark.cli export-leaderboard-artifact --help
```

导出参数格式可直接参照 official baseline runner，只是元信息要换成 current repo：

- engine: `vllm-hust`
- engine-version: 当前实际版本
- git-commit: `383b3c7acb08654da445c0048fc3f3eed9c4bb19`
- github_repository: 当前 fork 对应 repo
### 优先级 3：用 current artifact 和 official artifact 做数值对比

直接对比以下指标：

- throughput
- TTFT
- TBT/TPOT

official baseline 现成参考值：

- throughput: `205.43238789737052`
- TTFT: `281.0340084585497`
- TBT: `78.65327996609436`
### 优先级 4：再决定后续方向

分叉判断：

1. 如果 same-spec current 接近 baseline：
  - 修 website compare 口径
  - 或刷新 website data 里的 current artifact

2. 如果 same-spec current 仍显著慢：
  - 去 `vllm-hust` / `vllm-ascend-hust` 做 runtime regression 排查
  - 重点先查 serving flags、scheduler、Ascend plugin 差异、请求路径兼容性

3. 无论哪种情况，之后都应补上：
  - `Hard Constraints` 只展示 `vllm-hust` 的 UI 语义修正
## 5. 关键路径与文件

### website

- `/root/workspace/vllm-hust-website/scripts/aggregate_results.py`
- `/root/workspace/vllm-hust-website/tests/test_aggregate_results.py`
- `/root/workspace/vllm-hust-website/assets/leaderboard.js`
- `/root/workspace/vllm-hust-website/assets/leaderboard.css`
- `/root/workspace/vllm-hust-website/CHANGELOG.md`

### official baseline

- `/root/workspace/reference-repos/vllm-ascend/benchmarks/scripts/run-vllm-hust-goal-baseline.sh`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/tests/vllm-hust-goal-baseline.json`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/tests/vllm-hust-goal-constraints.stub.json`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/raw_benchmark_result.json`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/submission/run_leaderboard.json`

### current rerun scratch paths

- `/tmp/vllm-v0110`
- `/tmp/vllm-ascend-v0110`
- `/tmp/vllm-hust-same-spec-current`

### handoff context

- `/root/workspace/vllm-hust-dev-hub/docs/website-goal-baseline-handoff-20260506.md`

## 6. 已验证的关键事实

- official baseline 必须从 neutral cwd 启动，否则 editable import 会串到 workspace checkout
- official `v0.11.0` random dataset bench CLI 需要 `--random-input-len/--random-output-len`
- official baseline 需要 `--enforce-eager`
- current `vllm 0.20.1` api_server 不接受 `--disable-log-requests`
- goal progress pairing 已经通过 model name normalization 修好
- website 聚合测试已通过

## 7. 建议的接手动作

按下面顺序执行，不要跳：

1. 确认 current server 是否仍在占用 `ASCEND_RT_VISIBLE_DEVICES=1`
2. 如果仍在跑，先清理旧 server/client 进程
3. 重新单独跑 same-spec current benchmark，确保 stdout/stderr 被完整保留
4. 一旦拿到 `raw_benchmark_result.json`，立刻导出 current artifact
5. 将 current artifact 与 official artifact 做直接数值比较
6. 再决定修 website compare 口径还是查 runtime regression
7. 最后补 `Hard Constraints` 只展示 `vllm-hust` 的 UI 语义修正

以上是当前最接近真实状态的交接说明。下一位执行者不需要重新设计方案，只需要沿着“same-spec current artifact -> compare -> 定性问题来源”这条链继续即可。
# vLLM-HUST Website 目标基线对比任务交接说明

本文档用于把当前进行中的“website 顶部目标基线对比”任务完整交接给另一个 team。

更新时间：2026-05-06

## 1. 任务背景

最初问题来自 website leaderboard 顶部展示过于拥挤，出现了过多卡片，视觉上不聚焦。

随后需求被重新定义为：

- leaderboard 顶部不应该展示泛化的多引擎对比卡片
- 顶部应该只展示当前 `vllm-hust + vllm-ascend-hust` 相对官方目标基线的进展
- 这个目标基线不是随意挑一个旧版本，而是“2026 年 1 月初官方 Ascend 版本”
- 基线代码必须放在 `reference-repos` 中
- 最终需要形成一条正式的“性能对比测试 + 网站展示”链路，用于展示距离既定目标还有多远

经过实际排查后，当前采用的官方目标基线定义为：

- `vllm v0.11.0`
- `vllm-ascend v0.11.0`

选择依据是：它比 `0.9.0` 更符合“2026 年 1 月初官方 Ascend 基线”的实际发布时间窗口，并且当前本地 `reference-repos` 中可以直接拿到对应 tag。

## 2. 任务总目标

需要交付的不是单个页面修改，而是一整条端到端链路：

1. 在 `reference-repos/vllm-ascend` 中维护官方 baseline 的 benchmark spec 和 runner。
2. 用官方 `vllm v0.11.0 + vllm-ascend v0.11.0` 跑出真实 benchmark 结果。
3. 将结果导出为 `vllm-hust-website` 可消费的 leaderboard artifact。
4. 聚合这些 artifact，生成 website compare snapshot。
5. 让 website 顶部优先显示固定目标对比，而不是普通 top-2 compare。
6. 用该展示持续表达“当前 vllm-hust 距离目标还差多远”。

## 3. 当前已经完成的工作

### 3.1 website 聚合层已支持固定目标基线

已经在 `vllm-hust-website` 的聚合脚本中加入 `goal_progress` 数据层。

关键点如下：

- 新增固定目标基线常量：`Official Ascend Jan 2026`
- 仅识别满足以下条件的 baseline 条目：
  - `engine == vllm`
  - `engine_version` 以 `0.11.0` 开头
  - `metadata.github_repository == vllm-project/vllm-ascend`
- 在同一个 compare scope 内，从当前数据里选出：
  - 最新的 `vllm-hust` 条目
  - 最新的官方 baseline 条目
- 计算三类差距：
  - throughput
  - TTFT
  - TBT
- 生成 `remaining_gap_pct` 和 `meets_goal`

对应代码位置：

- `/root/workspace/vllm-hust-website/scripts/aggregate_results.py`

重点实现包括：

- `GOAL_BASELINE_TARGET`
- `is_goal_baseline_entry()`
- `compute_remaining_gap()`
- `select_goal_pair()`
- `build_goal_progress_snapshot()`

### 3.2 website 顶部 hero 已改为优先展示目标基线

前端已经完成以下行为改造：

- overview 区域会先尝试读取 `goal_progress`
- 若存在匹配 pair，则顶部直接显示：
  - 当前 `vllm-hust`
  - 官方 `Official Ascend Jan 2026 baseline`
  - throughput / TTFT / TBT 当前值与 gap
- 若不存在 baseline 数据，才退回原有的普通 compare 逻辑

对应代码位置：

- `/root/workspace/vllm-hust-website/assets/leaderboard.js`
- `/root/workspace/vllm-hust-website/assets/leaderboard.css`

### 3.3 hard constraints 顶部区域已顺手优化

这不是本任务主目标，但已经随手修完，可以直接保留：

- 原先是大面积卡片墙
- 现在改成可折叠的摘要式 `<details>` 结构
- 会优先把失败 scope 排到前面

这部分不需要另一个 team 再返工，除非产品重新改 UI 要求。

### 3.4 reference baseline 的 spec 和 runner 已落地

已经在 `reference-repos/vllm-ascend` 中增加以下文件：

- `benchmarks/tests/vllm-hust-goal-baseline.json`
- `benchmarks/tests/vllm-hust-goal-constraints.stub.json`
- `benchmarks/scripts/run-vllm-hust-goal-baseline.sh`

并在 `benchmarks/README.md` 中加入了使用说明。

这意味着 baseline 运行入口已经具备，不需要从零设计脚本。

### 3.5 基础测试已经补上并通过

已经新增 website 聚合回归测试，验证：

- 当同一 scope 下同时存在 `vllm-hust` 与官方 baseline 条目时
- 聚合结果中会生成 `goal_progress`
- `headline_pair` 指向正确的 current / baseline
- throughput 剩余 gap 计算符合预期

对应测试文件：

- `/root/workspace/vllm-hust-website/tests/test_aggregate_results.py`

已验证命令：

```bash
cd /root/workspace/vllm-hust-website
conda run -p /home/shuhao/miniconda3/envs/vllm-hust-dev \
  python -m pytest tests/test_aggregate_results.py -q
```

结果：

- `4 passed`

## 4. 当前还没有完成的工作

下面这些是另一个 team 真正需要继续推进的部分。

### 4.1 还没有真实 baseline artifact 被产出并接入 website

这是当前最大的未完成项。

虽然：

- baseline spec 已经写好
- runner 已经写好
- website 聚合和前端也已经 ready

但是：

- 还没有跑出一份真实的官方 baseline benchmark 结果
- 也还没有把真实 artifact 聚合进 website 的 `data/` 输出

因此当前页面顶部即使代码已经支持，也不会自动出现真实目标卡片，除非数据里存在官方 baseline 条目。

### 4.2 还没有完成“跑完 baseline -> 聚合 -> 本地页面验收”闭环

当前状态仍然停留在“代码准备好，但数据没落地”。

另一个 team 接手后，最优先的事情不是改代码，而是把闭环跑通：

1. 跑 baseline
2. 导出 artifact
3. 聚合 website 数据
4. 本地打开页面确认顶部 hero 正常显示

### 4.3 constraints 目前仍是 stub

当前 `vllm_hust_benchmark.leaderboard_export` 需要 `constraints_metrics` 才能导出 website artifact。

为了先打通数据格式链路，当前提供的是 stub：

- 所有约束指标字段存在
- 值全部为 `null`

这能满足导出要求，但并不代表真实 constraints 数据已经采集完成。

如果后续要把 baseline 同时纳入 hard constraints 统计或更正式报告，则需要另行补采真实约束数据。

### 4.4 还没有自动化

当前工作流仍是人工流程：

1. 手工运行官方 baseline runner
2. 手工导出 artifact
3. 手工运行 website 聚合脚本
4. 手工验证页面

如果后续希望长期维护，应考虑：

- 将 baseline runner 接入 benchmark pipeline
- 或定时生成 artifact
- 或在发布流程中自动刷新 website compare snapshot

这部分目前未做。

## 5. 当前涉及的仓库与职责边界

### 5.1 `vllm-hust-website`

职责：

- 消费 artifact
- 生成 compare snapshot
- 在前端顶部展示目标差距

不应该承担的职责：

- 不应该直接跑官方 baseline benchmark
- 不应该管理官方 baseline 环境安装

### 5.2 `reference-repos/vllm-ascend`

职责：

- 存放官方 baseline spec
- 存放官方 baseline runner
- 作为官方 baseline 逻辑的参考与执行入口

这是符合“基线代码应该放在 reference-repos 里面”的要求的。

### 5.3 `vllm-hust-benchmark`

职责：

- 提供 website artifact 的导出 CLI
- 负责把 benchmark 输出封装成 website 消费的数据格式

当前无需修改即可被 baseline runner 复用。

### 5.4 `reference-repos/vllm` 与 `reference-repos/vllm-ascend`

职责：

- 作为官方 `v0.11.0` 代码来源
- 不直接承载 fork 逻辑

当前已经准备好的官方 worktree：

- `/tmp/vllm-v0110`
- `/tmp/vllm-ascend-v0110`

## 6. 当前已准备好的运行环境

### 6.1 官方 baseline conda 环境

环境路径：

- `/root/miniconda3/envs/vllm-ascend-official-v0110`

当前确认情况：

- 已经可以 `import vllm`
- 已经可以 `import vllm_ascend`

用于验证的命令：

```bash
conda run -p /root/miniconda3/envs/vllm-ascend-official-v0110 python - <<'PY'
import importlib
for name in ("vllm", "vllm_ascend"):
    mod = importlib.import_module(name)
    print(name, getattr(mod, "__file__", "<namespace>"))
PY
```

### 6.2 官方代码 worktree

当前实际使用的是 `reference-repos` 里的官方 tag，而不是额外下载的仓库副本：

- `reference-repos/vllm` 的 `v0.11.0`
- `reference-repos/vllm-ascend` 的 `v0.11.0`

已经拉出的 worktree：

- `/tmp/vllm-v0110`
- `/tmp/vllm-ascend-v0110`

## 7. 另一个 team 接手后的建议执行顺序

下面是建议的工作拆分顺序。按这个顺序走，返工最少。

### 阶段 A：确认 baseline runner 可在官方环境中跑通

目标：确认不是“代码能 import”，而是“benchmark 能真实执行并产出结果”。

建议执行：

```bash
export GOAL_BASELINE_ENV_PREFIX=/root/miniconda3/envs/vllm-ascend-official-v0110
bash /root/workspace/reference-repos/vllm-ascend/benchmarks/scripts/run-vllm-hust-goal-baseline.sh \
  /root/workspace/reference-repos/vllm-ascend/benchmarks/tests/vllm-hust-goal-baseline.json
```

该命令应完成：

1. 启动官方 `vllm` OpenAI API server
2. 执行 benchmark client
3. 写出 `raw_benchmark_result.json`
4. 调用 `vllm_hust_benchmark.cli export-leaderboard-artifact`
5. 产出 website artifact

如果这一步失败，先不要改 website，优先解决环境或 benchmark 参数问题。

### 阶段 B：确认 baseline runner 的产物目录结构正确

预期结果目录：

- `/root/workspace/reference-repos/vllm-ascend/benchmarks/results/vllm-hust-goal-baseline/`

至少应该能看到：

- `raw_benchmark_result.json`
- `submission/` 目录
- `submission/` 下的 leaderboard artifact 文件

如果 artifact 没生成，优先检查：

- `vllm_hust_benchmark` 是否可 import
- `constraints stub` 是否被正确传入
- benchmark 输出文件名是否和 runner 中的预期一致

### 阶段 C：将 baseline artifact 聚合进 website 数据

拿到 artifact 后，运行 website 聚合脚本。

如果 baseline artifact 已经与其他 leaderboard artifact 放在同一个 source 目录，执行：

```bash
cd /root/workspace/vllm-hust-website
conda run -p /home/shuhao/miniconda3/envs/vllm-hust-dev \
  python scripts/aggregate_results.py \
  --source-dir <artifact-source-dir> \
  --output-dir data
```

接手 team 需要保证传入的 `source-dir` 中同时存在：

- 当前 `vllm-hust` artifact
- 官方 baseline artifact

否则 `goal_progress` 仍然不会出现。

### 阶段 D：本地打开 website 验收顶部 hero

本地服务建议这样启动：

```bash
cd /root/workspace/vllm-hust-website
python3 -m http.server 4173
```

注意：之前记录里有一条失败命令是 `python -m http.server 4173`，失败原因通常是当前 shell 没有 `python` 命令别名，因此建议直接使用 `python3`。

打开页面后应重点确认：

1. 顶部是否优先显示目标比较，而不是普通 compare。
2. 标签是否为：
   - `Current vllm-hust`
   - `Official Ascend Jan 2026 baseline`
3. 是否显示三类差距：
   - throughput
   - TTFT
   - TBT
4. 当 gap 为 0 时，是否显示 `Goal met`。
5. 当 gap 非 0 时，是否显示 `Remaining gap`。

### 阶段 E：决定是否扩展为多 scope baseline

当前 baseline spec 只覆盖一个示例场景：

- `Qwen/Qwen2.5-14B-Instruct`
- `FP16`
- `910B3`
- `random-online`

如果产品期望网站顶部在更多筛选组合下都有目标卡片，则需要继续补充更多 baseline spec，而不是推翻现有聚合逻辑。

建议做法：

1. 每个重点 scope 一份独立 baseline spec
2. 每份 spec 跑出对应 artifact
3. 让 website 通过现有 `scope_key` 自动匹配

### 阶段 F：决定是否自动化

在人工链路跑通之后，再决定是否追加自动化。

建议候选方向：

1. 在 benchmark pipeline 中定期刷新 baseline artifact。
2. 在 website 数据发布前自动执行一次 baseline compare 聚合。
3. 将 baseline artifact 存档到一个统一的 results 目录，并纳入版本化管理。

这一步不建议在真实 artifact 产出之前就先做。

## 8. 建议分工

如果另一个 team 需要拆成多个小任务，建议这样分：

### Workstream 1：官方 baseline 运行与环境确认

负责内容：

- 确认 `v0.11.0` 官方环境可稳定启动 server
- 跑通 benchmark
- 产出 raw result 和 leaderboard artifact

输入：

- `/root/miniconda3/envs/vllm-ascend-official-v0110`
- `/tmp/vllm-v0110`
- `/tmp/vllm-ascend-v0110`
- baseline spec / runner

输出：

- 一份真实 official baseline artifact

### Workstream 2：website 数据接入与页面验收

负责内容：

- 聚合官方 baseline artifact 与当前 vllm-hust artifact
- 本地启动页面
- 确认顶部 hero 正确展示

输出：

- 一份可验证的 website 数据快照
- 一组页面截图或验收记录

### Workstream 3：后续扩展与自动化

负责内容：

- 扩展更多 baseline scope
- 将 baseline 生成链路自动化
- 决定是否补真实 constraints 数据

这部分优先级最低。

## 9. 验收标准

另一个 team 接手后，可以用下面这组验收标准判断是否算完成。

### 最低交付标准

满足以下四条即可认为这期任务闭环：

1. 官方 baseline runner 能产出真实 artifact。
2. website 聚合结果中存在 `goal_progress`。
3. website 顶部显示固定目标卡片，而不是通用 compare。
4. 页面能正确显示当前与 baseline 的 throughput / TTFT / TBT 差距。

### 完整交付标准

在最低交付基础上，再满足以下条件可视为完整交付：

1. 有本地验收截图或录屏。
2. 已记录 baseline 运行命令、结果路径与 commit 信息。
3. 已明确后续是否继续扩展多 scope。
4. 已明确是否需要将 baseline 生成过程自动化。

## 10. 风险与注意事项

### 10.1 当前固定识别的是 `v0.11.0`

如果后续产品要把官方目标版本改成别的时间点，对应需要同步更新：

- `GOAL_BASELINE_TARGET`
- baseline spec 中的 `engine_version` / `github_ref`
- 可能还要调整 `git_commit`

### 10.2 当前 constraints 不是实测值

stub 只为打通导出链路，不代表 hard constraints 已完成基线评估。

### 10.3 当前只覆盖一个重点 scope

如果接手 team 直接拿这一版去支持多模型、多硬件、多 workload，会发现覆盖范围不够。这不是 bug，而是当前任务范围本来就先聚焦一条目标基线。

### 10.4 不建议把 baseline 逻辑塞回 fork 主代码

官方 baseline 的生成逻辑应该继续留在 `reference-repos`，避免把 reference 行为和 fork 产品逻辑耦合在一起。

## 11. 当前改动文件清单

### 已修改的 website 文件

- `/root/workspace/vllm-hust-website/scripts/aggregate_results.py`
- `/root/workspace/vllm-hust-website/assets/leaderboard.js`
- `/root/workspace/vllm-hust-website/assets/leaderboard.css`
- `/root/workspace/vllm-hust-website/tests/test_aggregate_results.py`

### 已新增或修改的 reference baseline 文件

- `/root/workspace/reference-repos/vllm-ascend/benchmarks/scripts/run-vllm-hust-goal-baseline.sh`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/tests/vllm-hust-goal-baseline.json`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/tests/vllm-hust-goal-constraints.stub.json`
- `/root/workspace/reference-repos/vllm-ascend/benchmarks/README.md`

## 12. 推荐给接手 team 的第一天执行清单

建议他们第一天不要大改代码，而是按下面清单执行：

1. 阅读本文档和上述改动文件。
2. 确认官方 baseline 环境里 `vllm` / `vllm_ascend` 可 import。
3. 运行一次 baseline runner。
4. 检查 artifact 是否生成。
5. 运行 website 聚合。
6. 本地启动 website，确认顶部 hero 是否显示目标差距。
7. 记录失败点或缺失依赖，再决定是否需要改 runner、spec 或环境。

## 13. 一句话交接摘要

代码通路已经打通，另一个 team 不需要重新设计方案；他们需要做的是把 `reference-repos/vllm-ascend` 里的官方 `v0.11.0` baseline runner 真正跑出 artifact，并把该 artifact 聚合进 `vllm-hust-website`，完成顶部目标差距展示的数据闭环。