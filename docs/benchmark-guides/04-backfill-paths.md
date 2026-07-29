# Backfill 路径详解

## backfill 与 same-spec runner 的边界关系

- 路径 D(历史 PR backfill)内部调用路径 A 的 `run-current-ascend-same-spec.sh` runner,benchmark 实现与 leaderboard export 路径都在 same-spec runner 里。
- 路径 C(单卡 backfill)自己直接调 `vllm bench` 子命令,不经过 same-spec runner。
- 路径 E(组织成员 delta)用 worktree 隔离(Va=稳定基础设施,Vb=被测代码),调 `vllm bench`。
- 三条 backfill 路径都最终产出 `submissions/` artifact,但提交者标识、commit 解析方式不同。

## 3 条 backfill 路径对照表

| 维度 | 路径 C:单卡历史 commit | 路径 D:历史 PR real-online | 路径 E:组织成员 delta |
|------|------------------------|---------------------------|----------------------|
| 目标 | 补 `vllm-hust` 历史 commit 在 910B2 单卡的缺失 workload | 跑历史 PR 的 real-online benchmark | 为 org member 的 commit 跑 benchmark,计算 delta |
| 入口脚本 | `python3 scripts/backfill_single_gpu.py <subcommand>` | `python3 scripts/backfill_historical_pr_benchmarks.py [options]` | `python3 scripts/run_org_member_benchmarks.py run [options]` |
| commit 解析方式 | 从 `leaderboard-data/snapshots/leaderboard_single.json` 的 `metadata.git_commit` 字段提取;`latest` 解析为 `origin/main` 最新 | 从 commit subject grep `perf|performance|optimi|throughput|latency|decode|scheduler|cache|prefix|kv` 发现重要 ref,或从 `--plan-file` 读 | 从 `git log` 解析 org member 的 PR commits 与 consecutive commits |
| 服务管理方式 | 直接 `vllm bench`(不启服务则跑 throughput/latency) | 必须走 `manage.sh --managed-dev-hub` 启服务,systemd unit 名必须以 `.service` 结尾 | worktree 隔离 + `vllm bench` |
| 产出目录 | `.benchmarks/backfill-single-gpu/` 与 `submissions/single-gpu-backfill-*` | `.benchmarks/historical-pr-backfill/` 与 `submissions/historical-pr-*` | `.benchmarks/checkpoint.json` 与 `submissions/` |
| 是否发布 HF | 否(需手工 push) | 可选(`--publish-each` 即时上传到 `intellistream/vllm-hust-benchmark-results`) | 否(需手工) |
| 典型用途 | 补某个 commit 缺的 workload | 跑历史 PR 的 real-online 数据 | 计算 org member delta = perf(org_group) - perf(previous_upstream_group) |

## 路径 C `backfill_single_gpu.py` 详细

### 子命令表(8 个)

| 子命令 | 用途 | 需要 NPU |
|--------|------|---------|
| `plan` | 列出缺失 cell,commit 列表来自 `leaderboard_single.json` | 否 |
| `fill` | 一键补全所有 commit 的缺失 workload(plan + run 组合) | 是 |
| `status` | 查看 checkpoint 进度 | 否 |
| `validate` | 验证 submissions 和 snapshots | 否 |
| `aggregate` | 从 submissions/ 重建 snapshots | 否 |
| `run` | 执行 benchmark | 是 |
| `push` | stage + commit + push | 否 |
| `restore` | 恢复原始 HEAD | 否 |

### 选项表

| 选项 | 说明 |
|------|------|
| `--commit <SHA>` | vllm-hust commit(可选,默认 latest → origin/main) |
| `--ascend-commit <SHA>` | ascend 插件 commit(可选,默认 latest → origin/main) |
| `--workload <NAME>` | 指定 workload(可选,省略则补全所有缺失 workload) |
| `--force` | 重新运行已完成的 cell |
| `--fail-fast` | 遇到第一个失败停止 |
| `--npu-device <N>` | 指定 NPU 设备索引 |
| `--force-mismatched-plugin-commit` | 仅 `run` 子命令有,允许把同一 vllm-hust commit 重新绑定到另一个 plugin commit |

### 可复制命令示例

```bash
# 查看缺失的 benchmark 数据
python3 scripts/backfill_single_gpu.py plan
python3 scripts/backfill_single_gpu.py plan --group

# 查看 checkpoint 进度
python3 scripts/backfill_single_gpu.py status

# 验证 submissions 和 snapshots
python3 scripts/backfill_single_gpu.py validate

# 一键补全所有缺失的 benchmark 数据(需要 NPU)
python3 scripts/backfill_single_gpu.py fill
nohup python3 scripts/backfill_single_gpu.py fill > backfill.log 2>&1 &
```

```bash
# 默认 latest(两者都自动解析为 origin/main),补全所有缺失 workload
python3 scripts/backfill_single_gpu.py run

# 指定 commit,ascend 自动解析为 latest origin/main
python3 scripts/backfill_single_gpu.py run \
    --commit 51621c35b --workload random-latency

# 补全指定 commit 所有缺失 workload(ascend 自动解析为 latest origin/main)
python3 scripts/backfill_single_gpu.py run --commit 51621c35b

# 两个都指定
python3 scripts/backfill_single_gpu.py run \
    --commit 83cf83f --ascend-commit 03a12f9 --workload random-latency
```

### 支持的 workload

```
random-latency    sharegpt-throughput   sonnet-throughput
random-online     sharegpt-online       prefix-repetition-online
instructcoder-online
```

### 环境变量表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BACKFILL_PYTHON` | `~/miniconda3/envs/vllm-hust-dev/bin/python` | Python 解释器路径 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像 |
| `VLLM_USE_V1` | `1` | 启用 V1 引擎 |

### 模块常量

| 常量名 | 值 | 含义 |
|---|---|---|
| `MODEL_NAME` | `Qwen/Qwen2.5-14B-Instruct` | 默认模型 |
| `MODEL_PARAMETERS` | `14B` | 模型参数量 |
| `MODEL_PRECISION` | `FP16` | 模型精度 |
| `HARDWARE_CHIP_MODEL` | `910B2` | 硬件芯片型号 |
| `DEFAULT_GPU_MEMORY_UTILIZATION` | `0.6` | same-spec 的 gpu_memory_utilization |
| `DEFAULT_MAX_MODEL_LEN` | `32768` | same-spec 的 max_model_len(不是 30720) |
| `SUBMITTER` | `vllm-hust-org-member` | 默认 submitter 标识 |

这些是代码里硬编码的常量,不是环境变量,不能通过 env 覆盖。

## 路径 D `backfill_historical_pr_benchmarks.py` 详细

### 关键开关表

| 开关 | 含义 | 默认 |
|------|------|------|
| `--execute` | 真正执行(默认 dry-run) | dry-run |
| `--plan-file <path>` | 读 curated plan JSON | (空) |
| `--discover-from-log` | 从 commit subjects grep 重要 ref | 关 |
| `--max-discovered-refs <N>` | 最多发现多少 ref | 12 |
| `--workload <name>` | 只跑指定 workload(可重复) | 全部 |
| `--include-multi-chip` | 包含多卡 sonnet specs | 排除 |
| `--worktree-root <path>` | git worktree 根(managed 模式必须可见于容器内,如 `/home/shuhao/...`) | (空) |
| `--managed-dev-hub` | 通过 `manage.sh` 启服务(强烈推荐) | 关 |
| `--managed-container <name>` | dev-hub 容器名 | `vllm-hust-backfill` |
| `--managed-systemd-unit <name>` | systemd unit 名(必须以 `.service` 结尾) | `vllm-hust-backfill.service` |
| `--managed-npu-devices <ids>` | NPU 设备号 | `0` |
| `--managed-max-model-len <N>` | max_model_len | 32768 |
| `--managed-max-num-seqs <N>` | max_num_seqs | 16 |
| `--managed-gpu-mem-util <f>` | gpu_memory_utilization | `0.6` |
| `--managed-enforce-eager` | 强制 eager(仅诊断用,正式 leaderboard 禁用) | 关 |
| `--publish-each` | 每个结果即时上传 HF | 关 |
| `--sync-website-each` | 每个结果后同步 website mirror | 关 |
| `--commit-push-each` | 每个结果后 commit + push benchmark 与 website 仓 | 关 |
| `--rerun-completed` | 重跑已完成 cell | 关 |

### 典型命令

```bash
# Dry-run 预览默认 current-ref 矩阵
cd /home/shuhao/vllm-hust-benchmark
python scripts/backfill_historical_pr_benchmarks.py

# Dry-run 预览从 commit log 发现的重要 ref
python scripts/backfill_historical_pr_benchmarks.py \
  --discover-from-log \
  --max-discovered-refs 12

# Dry-run 预览 curated plan
python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file docs/historical-pr-backfill-plan.sample.json
```

```bash
# 真跑 + 全量发布(HF + website + git push)
PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file docs/historical-pr-backfill-plan.json \
  --managed-dev-hub \
  --dev-hub-dir /home/shuhao/vllm-hust-dev-hub \
  --managed-container vllm-hust-backfill \
  --managed-systemd-unit vllm-hust-backfill.service \
  --managed-npu-devices 0 \
  --server-port 8001 \
  --runtime-python /home/shuhao/miniconda3/envs/vllm-hust-dev/bin/python \
  --current-env-prefix /home/shuhao/miniconda3/envs/vllm-hust-dev \
  --result-root /data/shared_datasets/vllm-hust-benchmark/historical-pr-backfill \
  --worktree-root /home/shuhao/.cache/vllm-hust-benchmark-worktrees/historical-pr-backfill \
  --execute \
  --publish-each \
  --sync-website-each \
  --commit-push-each
```

```bash
# 单 workload 调试
PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file docs/historical-pr-backfill-plan.json \
  --workload sharegpt-online \
  --managed-dev-hub \
  --managed-container vllm-hust-backfill \
  --managed-systemd-unit vllm-hust-backfill.service \
  --managed-npu-devices 0 \
  --server-port 8001 \
  --runtime-python /home/shuhao/miniconda3/envs/vllm-hust-dev/bin/python \
  --current-env-prefix /home/shuhao/miniconda3/envs/vllm-hust-dev \
  --result-root /data/shared_datasets/vllm-hust-benchmark/historical-pr-backfill \
  --worktree-root /home/shuhao/.cache/vllm-hust-benchmark-worktrees/historical-pr-backfill \
  --execute \
  --publish-each \
  --sync-website-each
```

### 默认单卡 workload 清单

```
agent-research-online
instructcoder-online
prefix-repetition-online
random-latency
random-online
sharegpt-online
sharegpt-throughput
sonnet-throughput
visionarena-online
```

多卡 sonnet specs 默认排除,需 `--include-multi-chip` 显式开启。

## 路径 E `run_org_member_benchmarks.py` 详细

### attribution 模型

- PR commits → 1 benchmark per PR,attributed to PR
- Consecutive commits(无 PR)by same user → 1 benchmark per session
- org member delta = perf(org_group) - perf(previous_upstream_group)

### 上游 baseline 查找顺序

- 先查本地 `submissions/` 目录
- 再查 leaderboard snapshot(本地或 GitHub raw)
- 都没有就跑上游 benchmark

### 典型命令

```bash
# Dry-run
cd vllm-hust-benchmark
GH_TOKEN=<ghp_xxx> python3 run_org_member_benchmarks.py run --dry-run

# 带上游 baseline commits
GH_TOKEN=<ghp_xxx> python3 run_org_member_benchmarks.py run \
    --upstream-commits <abc123>,<def456>

# Resume
GH_TOKEN=<ghp_xxx> python3 run_org_member_benchmarks.py run \
    --resume --model Qwen/Qwen2.5-7B-Instruct

# 仅生成报告
python3 run_org_member_benchmarks.py report \
    --checkpoint .benchmarks/checkpoint.json
```

## plugin commit canonical guard 规则

- **canonical 来源**:snapshot 中已有的、针对该 `metadata.git_commit` 最早提交的那条 leaderboard entry 的 `runtime_provenance.plugin.commit`
- **首次跑**:snapshot 中没有任何记录 → 没有可比对的 canonical,guard 直接 pass,首次跑的结果自然成为后续 canonical
- **snapshot miss + time-align fallback**:选中的 plugin commit 也会作为 entry 写入新 submission,进而成为下次的 canonical
- **`--force-mismatched-plugin-commit`**:仅 `run` 子命令(路径 C)有,允许把同一 vllm-hust commit 重新绑定到另一个 plugin commit;使用时三元组 `(hust_commit, canonical_plugin_commit, override_plugin_commit)` 会被追加写到 `.benchmarks/backfill-single-gpu/state.json` 的 `audit.plugin_override` 列表中
- **`fill` 子命令没有此 flag**:因为它是「按 snapshot 一致」为前提的全自动模式,任何不一致都应当人工处理而不是自动 override
- **`plan` 输出警告**:当 snapshot canonical 与 chain 解析结果不一致(即 `run` 会拒绝)时,会在对应 commit 块的 plugin 预览行下加一行 `⚠`
- **路径 D 与 E**:路径 D 因为走 `manage.sh` 启服务,plugin commit 由 worktree 决定,不走 canonical guard;路径 E 同理

## 已知约束

- 当前活跃硬件是 **910B2**,不得引入 `910B3` 默认
- 正式 leaderboard 数据禁用 `--enforce-eager`(仅诊断用)
- 不得发布 `v0.11.0` / `910B3` / BF16 / missing-same-spec 的归档记录作为真实跑替代
- `docs/official-baselines/` 只放公开可比 spec(vLLM/vLLM-Ascend v0.18.0, 910B2, FP16)
- managed-server 模式下,host 端 client 只是 HTTP 负载生成器,不得 import 历史 `vllm-ascend-hust` 源码树
- 失败的启动/健康探测/客户端 benchmark 不得发布、镜像到 website data、或 commit
