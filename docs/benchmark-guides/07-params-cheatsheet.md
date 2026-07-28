# 路径 vs 案例速查表

| 路径 | 目标 | 入口脚本 | 典型 demo |
|------|------|---------|----------|
| A | vllm-hust 执行版 | `run-current-ascend-same-spec.sh` | `bash scripts/run-current-ascend-same-spec.sh <spec.json>` |
| B | vllm 官方 v0.18.0 baseline | `run-official-v0180-baselines.sh` | `bash scripts/run-official-v0180-baselines.sh --devices 0 --repeat-count 3` |
| C | 单卡历史 commit backfill | `backfill_single_gpu.py` | `python3 scripts/backfill_single_gpu.py run --commit <sha> --workload <name>` |
| D | 历史 PR real-online backfill | `backfill_historical_pr_benchmarks.py` | `PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py --plan-file <plan.json> --managed-dev-hub --execute` |
| E | 组织成员 delta 基准 | `run_org_member_benchmarks.py` | `GH_TOKEN=<token> python3 scripts/run_org_member_benchmarks.py run --dry-run` |
| F | msprof profiling | `run-current-ascend-same-spec-msprof.sh` | `bash scripts/run-current-ascend-same-spec-msprof.sh <spec.json>` |
| G | campaign 重复跑 | `run-campaign-repetitions.sh` | `bash scripts/run-campaign-repetitions.sh <spec.json> --repetitions 3` |
| H | matrix 多 spec 批量跑 | `run-current-ascend-same-spec-matrix.sh` | `bash scripts/run-current-ascend-same-spec-matrix.sh docs/spec-matrix/` |

# 入口 runner 类参数总表

| 脚本 | 路径 | 位置参数 | 关键 flags | 关键环境变量 | 默认 conda env |
|---|---|---|---|---|---|
| `run-current-ascend-same-spec.sh` | A | `$1=SPEC_FILE`(默认官方 random-online spec) | 无 flag(纯环境变量驱动) | `CURRENT_ENV_PREFIX`、`CURRENT_RUNTIME_PYTHON`、`CURRENT_VLLM_HUST_REPO`、`CURRENT_VLLM_ASCEND_HUST_REPO`、`CURRENT_SERVER_PORT=8001`、`CURRENT_SUBMITTER=same-spec-current`、`CURRENT_USE_MANAGED_SERVER=0` | `vllm-hust-dev` |
| `run-official-v0180-baselines.sh` | B | `[<spec-file-or-dir> ...]`(默认 `docs/official-baselines`) | `--repeat-count`、`--devices`、`--publish-website`、`--review-existing`、`--force-repair-env`、`--no-prepare-env` | `GOAL_BASELINE_ENV_PREFIX`、`OFFICIAL_MODEL_PATH`、`ASCEND_VISIBLE_DEVICES`、`SKIP_OFFICIAL_ASCEND_C_EXTENSION_BUILD=1`、`HF_ENDPOINT=https://hf-mirror.com` | `vllm-ascend-official-v0180` |
| `run-current-ascend-same-spec-msprof.sh` | F | `$1=SPEC_FILE` | 无 flag | `MSPROF_EXECUTABLE=msprof`、`MSPROF_FLAGS="--ascendcl=on --runtime-api=on --task-time=l1 --hccl=on --type=text"`、`DRY_RUN=0` | 同 A |
| `run-campaign-repetitions.sh` | G | `<spec-file>`(必需) | `--campaign-prefix`、`--repetitions=3`、`--cooldown=60` | `CURRENT_SERVER_PORT=8001` | 透传到 A |
| `run-single-repetition.sh` | G 内部 | `<spec-file> <campaign-prefix> <run-index>`(三者皆必需) | 无 flag | 透传所有 `CURRENT_*` | 同 A |
| `run-current-ascend-same-spec-matrix.sh` | H | `<spec-file-or-dir> ...`(至少 1 个) | 无 flag | `MATRIX_RESULT_ROOT`、`PUBLISH_WEBSITE=0`、`CURRENT_ENV_PREFIX` | `vllm-hust-dev` |
| `run-official-ascend-goal-baseline.sh` | B 底层 | `$1=SPEC_FILE` | 无 flag | `GOAL_BASELINE_ENV_PREFIX`(必需)、`OFFICIAL_VLLM_REPO`、`OFFICIAL_VLLM_ASCEND_REPO`、`OFFICIAL_SERVER_PORT=8000` | `vllm-ascend-official-v0180` |
| `run-official-ascend-goal-baseline-matrix.sh` | B matrix | `[<spec-file-or-dir> ...]` | 无 flag | `GOAL_BASELINE_ENV_PREFIX`(必需)、`REPEAT_COUNT=3`、`CANONICAL_SUBMISSIONS_ROOT` | `vllm-ascend-official-v0180` |

# 入口 runner 类 use demo

```bash
# 路径 A:vllm-hust 执行版
cd vllm-hust-benchmark
bash scripts/run-current-ascend-same-spec.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json
```

```bash
# 路径 B:vllm 官方 v0.18.0 baseline
cd vllm-hust-benchmark
bash scripts/run-official-v0180-baselines.sh --devices 0 --repeat-count 3 \
  docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json
```

```bash
# 路径 C:单卡历史 commit backfill
cd vllm-hust-benchmark
python3 scripts/backfill_single_gpu.py run --commit 51621c35b --workload random-latency
```

```bash
# 路径 D:历史 PR real-online backfill
cd vllm-hust-benchmark
PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file docs/historical-pr-backfill-plan.json \
  --managed-dev-hub --execute
```

```bash
# 路径 E:组织成员 delta 基准
cd vllm-hust-benchmark
GH_TOKEN=<token> python3 scripts/run_org_member_benchmarks.py run --dry-run
```

```bash
# 路径 F:msprof profiling
cd vllm-hust-benchmark
bash scripts/run-current-ascend-same-spec-msprof.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json
```

```bash
# 路径 G:campaign 重复跑
cd vllm-hust-benchmark
bash scripts/run-campaign-repetitions.sh \
  docs/official-baselines/full-stack-jul-2026-random-online-qwen25-14b-2chip-910b2.json \
  --campaign-prefix full-stack-jul-2026 --repetitions 3
```

```bash
# 路径 H:matrix 多 spec 批量跑
cd vllm-hust-benchmark
bash scripts/run-current-ascend-same-spec-matrix.sh docs/spec-matrix/
```

# Backfill 类参数详解

## 4.1 脚本 9 `backfill_single_gpu.py`(8 个子命令)

模块常量(不是环境变量,代码里硬编码):

- `MODEL_NAME="Qwen/Qwen2.5-14B-Instruct"`
- `MODEL_PARAMETERS="14B"`
- `MODEL_PRECISION="FP16"`
- `HARDWARE_CHIP_MODEL="910B2"`
- `DEFAULT_GPU_MEMORY_UTILIZATION="0.6"`
- `DEFAULT_MAX_MODEL_LEN="32768"`
- `SUBMITTER="vllm-hust-org-member"`

子进程注入(通过 `env.setdefault`,不覆盖已有值):

- `HF_ENDPOINT=https://hf-mirror.com`
- `VLLM_USE_V1=1`

子命令表:

| 子命令 | 参数 | 类型/默认 | 含义 |
|---|---|---|---|
| `plan` | `--group` | flag | 按 commit 分组 |
| `status` | (无) | — | 显示 checkpoint 进度 |
| `aggregate` | (无) | — | 重建 snapshots |
| `validate` | (无) | — | 校验 submissions + snapshots |
| `restore` | (无) | — | 恢复 HEAD |
| `push` | `-m`/`--message` | str | commit message |
| `push` | `--dry-run` | flag | 不实际 push |
| `run` | `--commit` | str(默认 latest → origin/main) | vllm-hust commit |
| `run` | `--ascend-commit` | str(默认 latest) | plugin commit |
| `run` | `--workload` | choices | 指定 workload |
| `run` | `--force` | flag | 重跑已完成 cell |
| `run` | `--fail-fast` | flag | 首次失败即停止 |
| `run` | `--npu-device` | int(默认 None) | NPU 设备索引 |
| `run` | `--force-mismatched-plugin-commit` | flag | 跳过 plugin guard |
| `fill` | `--workload` | choices | 限定 workload |
| `fill` | `--force`/`--fail-fast`/`--npu-device` | 同 run | 同上 |

注:`fill` **没有** `--force-mismatched-plugin-commit`。

## 4.2 脚本 10 `backfill_historical_pr_benchmarks.py`(6 分组参数)

无子命令,flat argparse。6 个分组:

**execute/plan 组**:`--execute`(flag)、`--plan-file`(Path)、`--state-file`

**discover 组**:`--discover-from-log`(flag)、`--max-discovered-refs`(int,默认 12)、`--discover-grep`(默认 `perf|performance|optimi|throughput|latency|decode|scheduler|cache|prefix|kv`)、`--include-multi-chip`(flag)

**workload 组**:`--spec-dir`(默认 `docs/official-baselines`)、`--workload`(action=append)、`--result-root`(默认 `.benchmarks/historical-pr-backfill`)、`--worktree-root`、`--rerun-completed`(flag)

**managed(dev-hub)组**:`--managed-dev-hub`(flag)、`--dev-hub-dir`、`--managed-npu-devices`(默认 `0`)、`--managed-container`(默认 `vllm-hust-backfill`)、`--managed-systemd-unit`(默认 `vllm-hust-backfill.service`)、`--managed-max-model-len`(默认 32768)、`--managed-max-num-seqs`(默认 16)、`--managed-gpu-mem-util`(默认 `0.6`)、`--managed-enforce-eager`(默认 False)、`--managed-enable-prefix-caching`(默认 False)、`--managed-enable-chunked-prefill`(默认 False)、`--managed-disable-ascend-fusion`(默认 False)

**publish 组**:`--publish-each`(flag)、`--sync-website-each`(flag)、`--commit-push-each`(flag)、`--hf-repo`(默认 `intellistream/vllm-hust-benchmark-results`)、`--website-repo`

**runtime/env 组**:`--runtime-python`(默认 `~/miniconda3/envs/vllm-hust-dev/bin/python`)、`--current-env-prefix`、`--server-port`、`--submitter`(默认 `historical-pr-backfill`)

## 4.3 脚本 11 `run_org_member_benchmarks.py`(2 个子命令)

**`run` 子命令**:`--dry-run`、`--resume`、`--fail-fast`、`--vllm-hust-repo`、`--vllm-ascend-hust-repo`、`--benchmark-repo`、`--scenario`(默认 `random-online`)、`--model`(默认 `Qwen/Qwen2.5-14B-Instruct`)、`--chips`(int,默认 1)、`--since`(默认 `2026-01-01`)、`--exclude`(默认 `ShuhaoZhangTony,moonandlife`)、`--checkpoint`、`--upstream-commits`、`--include-upstream`(int,默认 1)

**`report` 子命令**:`--checkpoint`、`--output`、`--html`、`--model`、`--scenario`

环境变量:`GH_TOKEN`(run 必需)、`HF_ENDPOINT`(默认 `https://hf-mirror.com`)

# Backfill 类 use demo

```bash
# 路径 C:补单个 commit 的单个 workload
python3 scripts/backfill_single_gpu.py run --commit 51621c35b --workload random-latency

# 路径 C:一键补全所有缺失 workload
python3 scripts/backfill_single_gpu.py fill

# 路径 C:查看缺失 cell
python3 scripts/backfill_single_gpu.py plan --group
```

```bash
# 路径 D:dry-run 预览
python scripts/backfill_historical_pr_benchmarks.py

# 路径 D:真跑 + 全量发布
PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file docs/historical-pr-backfill-plan.json \
  --managed-dev-hub --execute \
  --publish-each --sync-website-each --commit-push-each
```

```bash
# 路径 E:dry-run
GH_TOKEN=<token> python3 run_org_member_benchmarks.py run --dry-run

# 路径 E:带上游 baseline
GH_TOKEN=<token> python3 run_org_member_benchmarks.py run --upstream-commits abc123,def456
```

# 辅助工具类参数总表

| 脚本 | 用途 | 参数 | 典型用法 |
|---|---|---|---|
| `repair_same_spec_hash.py` | 原子修复 same-spec hash | `--old-hash`(必)、`--server-parameters-json`(必)、`--root`(append,必)、`--expected-payloads`(必,int)、`--execute`(flag) | `python repair_same_spec_hash.py --old-hash abc --server-parameters-json '{}' --root submissions/ --expected-payloads 3 --execute` |
| `archive_superseded_coexistence.py` | 归档被替代的共存冲突 | `--dry-run` / `--apply`(互斥,必选其一) | `python archive_superseded_coexistence.py --dry-run` |
| `validate_public_leaderboard_snapshots.py` | 校验 public 快照 | `--snapshot-dir`(默认 `leaderboard-data/snapshots`) | `python validate_public_leaderboard_snapshots.py` |
| `validate_trend_entries.py` | 校验 trend entries | `--input`(Path,必) | `python validate_trend_entries.py --input trend.json` |
| `collect-run-artifact.sh` | 收集 artifact | `<artifact-dir>`(必)、`--mark-failed <reason>` | `bash collect-run-artifact.sh submissions/xxx/` |
| `validate-run-artifact.sh` | 校验 artifact 目录 | `<artifact-dir>`(必) | `bash validate-run-artifact.sh submissions/xxx/` |
| `validate-local.sh` | 本地 CI 验证 | `--skip-pre-commit`、`--skip-tests`、`--skip-hook-templates` | `./scripts/validate-local.sh --skip-tests` |
| `setup-official-v0180-baseline.sh` | 一键设置 v0.18.0 env | `--skip-model` | `bash setup-official-v0180-baseline.sh` |
| `prepare-official-ascend-baseline-env.sh` | 底层 env 准备 | 无 CLI(全环境变量) | 被脚本 19/2/7/8 调用 |
| `run_latest_benchmark.sh` | 旧版硬编码跑 3 场景 | 无 CLI | **建议废弃**,改用脚本 9 或 6 |
| `run_vllm_cli_compat.py` | vLLM CLI 兼容包装器 | 透传 `bench serve|latency|throughput ...` | `python run_vllm_cli_compat.py bench serve --model ...` |
| `convert_trace_to_workload.py` | trace 转 benchmark dataset | `--input/-i`、`--output-dir/-o`、`--min-input-tokens`、`--min-output-tokens` | `python convert_trace_to_workload.py -i traces/in.jsonl` |
| `evoscientist_trace_handler.py` | LangChain callback(模块) | 非 CLI,`WorkloadTraceHandler(output_path, flush_every=1)` | `from evoscientist_trace_handler import WorkloadTraceHandler` |
| `run_evoscientist_trace.py` | 跑 EvoScientist 捕获 trace | `--prompt/-p`、`--output/-o`、`--base-url`、`--model`(默认 `Qwen3-32B`)、`--max-iterations`(默认 50) | `python run_evoscientist_trace.py --model Qwen3-32B` |

# 配置一致性对照表

| 检查项 | 状态 | 详情 |
|---|---|---|
| Python 解释器/env 命名 | **不一致(7 种)** | `CURRENT_ENV_PREFIX`(脚本 A/H)、`GOAL_BASELINE_ENV_PREFIX`(脚本 B)、`BACKFILL_PYTHON`(脚本 C)、`--runtime-python`(脚本 D)、`--current-env-prefix`(脚本 D)、`CURRENT_RUNTIME_PYTHON`(派生自 `CURRENT_ENV_PREFIX`)、`OFFICIAL_RUNTIME_PYTHON`(派生自 `GOAL_BASELINE_ENV_PREFIX`) |
| 模型路径命名 | **不一致(4 种)** | `CURRENT_MODEL_PATH`(脚本 A)、`OFFICIAL_MODEL_PATH`(脚本 B)、`--model-path`(脚本 B flag)、`--model`(脚本 E) |
| 端口默认值 | **不一致(4 种,同机混跑冲突)** | `CURRENT_SERVER_PORT=8001`(脚本 A/G)、`OFFICIAL_SERVER_PORT=8000`(脚本 B 底层)、`--server-port`(脚本 D,默认 `""`)、`BENCHMARK_SERVER_PORT=8000`(脚本 B 准备)。**同机混跑 current 与 official 系会端口冲突** |
| submitter 来源 | **不一致(4 种)** | `CURRENT_SUBMITTER=same-spec-current`(脚本 A)、`--submitter=historical-pr-backfill`(脚本 D)、spec 文件 `export.submitter`(脚本 B)、硬编码 `SUBMITTER="vllm-hust-org-member"`(脚本 C) |
| repo 路径命名 | **不一致(6 种)** | `CURRENT_VLLM_HUST_REPO`、`--core-repo`、`OFFICIAL_VLLM_REPO`、`--vllm-hust-repo`、`HUST_REPO`(脚本 21 硬编码)、`VLLM_REPO` |
| `VLLM_USE_V1` | 部分一致 | 仅脚本 C 与脚本 21 显式设置;其他脚本未显式设 |
| `HF_ENDPOINT` | **一致** | 默认 `https://hf-mirror.com`,出现在脚本 A/B/C/D/E/21 |
| `MAX_MODEL_LEN` 默认值 | **不一致(文档错误)** | 文档说 30720,代码常量 `DEFAULT_MAX_MODEL_LEN="32768"`,`validate_public_leaderboard_snapshots.py` 把 30720 标记为 `RETIRED_PUBLIC_MAX_MODEL_LEN` |

# 重复功能点分析

| 组别 | 重叠描述 | 是否真重复 | 建议处理 |
|---|---|---|---|
| 1 | `run-current-ascend-same-spec-matrix.sh`(H)vs `run-official-ascend-goal-baseline-matrix.sh`(B matrix) | 部分重复 | 抽公共 matrix 框架,official 版额外保留 canonical promotion 逻辑 |
| 2 | `run-campaign-repetitions.sh`(G)vs `backfill_single_gpu.py --force`(C) | 不重叠 | 保留;G 是同 commit 同 spec N 次,C 是 commit × workload 网格 |
| 3 | `run_latest_benchmark.sh`(脚本 21)vs `backfill_single_gpu.py`(C) | **真重复** | **废弃脚本 21**,改用脚本 9(backfill)或 6(matrix) |
| 4 | `backfill_single_gpu.py fill`(C)vs `backfill_historical_pr_benchmarks.py --execute`(D) | 不重叠 | 保留;C 面向单 GPU 矩阵补缺,D 面向 historical PR + managed dev-hub + HF publication |
| 5 | `run_org_member_benchmarks.py`(E)vs `backfill_historical_pr_benchmarks.py`(D) | 部分重复 | 可考虑合并 attribution(E)与 publication(D),但当前保留 |

# 参数命名统一建议

- Python 解释器/env:统一为 `<DOMAIN>_ENV_PREFIX` + 派生 `<DOMAIN>_RUNTIME_PYTHON` 模式,废弃直传路径
- 模型路径:统一为 `--model-path`(flag)或 `<DOMAIN>_MODEL_PATH`(env)
- 端口:统一为 8000 或显式区分并在文档说明
- submitter:统一为单一来源(spec 文件优先,env 覆盖,禁止硬编码)
- `MAX_MODEL_LEN`:修正文档,把 32768 标为唯一允许值
