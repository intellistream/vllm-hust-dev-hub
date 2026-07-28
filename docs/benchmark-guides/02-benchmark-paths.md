# 手动 Benchmark 路径对比

## 路径 vs 案例

阅读本指南前先分清两个概念:

- **路径(path)**:执行链路不同 —— 入口脚本不同 / 服务管理方式不同 / 产出 artifact 不同。本指南列出 8 条路径(A-H)。
- **案例(case)**:同一路径下的不同使用场景。例如路径 A 的"单 spec 跑"与"manage.sh 冒烟"是同一路径的两个案例;路径 C 的 `plan`/`run`/`fill` 是同一路径的多个子命令案例。

后续每条路径会标明它是路径还是案例变体。

workspace 的手动 benchmark 路径都在 `vllm-hust-benchmark` 仓里,大多吃同一份 spec JSON,但目标、conda env、源码位置、产出目录不同。一句话:`vllm-hust 执行版走 same-spec runner,vllm 官方 baseline 走 official-v0180-baselines runner,其余路径在此之上做 backfill / profiling / 重复 / 批量`。

## 8 条路径完整目录

| 路径 | 目标 | 入口脚本 | conda env | 源码位置 | 产出目录 | 典型用途 |
|------|------|---------|----------|---------|---------|---------|
| A | vllm-hust 执行版(我们的 fork) | `vllm-hust-benchmark/scripts/run-current-ascend-same-spec.sh <spec.json>` | `vllm-hust-dev` | `$WORKSPACE_ROOT/vllm-hust` + `vllm-ascend-hust`(PYTHONPATH 注入) | `.benchmarks/current-ascend-same-spec/` 与 `submissions/` | 验证 fork 优化、回归测试、贡献 vllm-hust 一侧数据 |
| B | vllm 官方 v0.18.0 baseline | `vllm-hust-benchmark/scripts/run-official-v0180-baselines.sh [options] [<spec>...]` | `vllm-ascend-official-v0180` | `reference-repos/vllm@v0.18.0` + `reference-repos/vllm-ascend@v0.18.0`(PYTHONPATH) | `.benchmarks/official-ascend-goal-baseline/` 与 `submissions/official-ascend-*` | 建立或复核官方 v0.18.0 baseline |
| C | 单卡历史 commit backfill | `python3 scripts/backfill_single_gpu.py <subcommand>` | `vllm-hust-dev`(`BACKFILL_PYTHON` 控制) | `vllm-hust` + `vllm-ascend-hust`(脚本会 git checkout 目标 commit) | `.benchmarks/backfill-single-gpu/` 与 `submissions/single-gpu-backfill-*` | 补某个 commit 的缺失 workload,详见 [04-backfill-paths.md](04-backfill-paths.md) |
| D | 历史 PR real-online backfill | `python3 scripts/backfill_historical_pr_benchmarks.py [options]` | `vllm-hust-dev` | detached git worktrees(不污染主 checkout) | `.benchmarks/historical-pr-backfill/` 与 `submissions/historical-pr-*` | 跑历史 PR 的 real-online 数据,详见 [04-backfill-paths.md](04-backfill-paths.md) |
| E | 组织成员 delta 基准 | `python3 scripts/run_org_member_benchmarks.py run [options]` | `vllm-hust-dev` | `vllm-hust` worktree(Va=稳定基础设施,Vb=被测代码) | `.benchmarks/checkpoint.json` 与 `submissions/` | 计算 org member delta = perf(org_group) - perf(previous_upstream_group) |
| F | msprof profiling | `bash scripts/run-current-ascend-same-spec-msprof.sh <spec.json>` | `vllm-hust-dev` | 同路径 A | `.benchmarks/current-ascend-msprof/<run-id>/`(`msprof_raw/` + `benchmark/`) | 性能剖析,产出 msprof 文本 trace + 同 spec benchmark 结果 |
| G | campaign 重复跑 | `bash scripts/run-campaign-repetitions.sh <spec> [--repetitions N]` | `vllm-hust-dev` | 同路径 A | `submissions/<campaign-prefix>-<workload>-<chip>chip-<ts>/`(N 份) | 同 spec 重复 N 次取中位数,内部调 `run-single-repetition.sh` |
| H | matrix 多 spec 批量跑 | `bash scripts/run-current-ascend-same-spec-matrix.sh <spec-dir-or-files...>` | `vllm-hust-dev` | 同路径 A | `.benchmarks/<matrix-run-id>/<spec-slug>/`(每 spec 一份) | 一次跑多个 spec,内部调路径 A 的 runner |

## 路径 A 详细:vllm-hust 执行版

### 环境变量

| 变量名 | 含义 | 默认值 |
|--------|------|--------|
| `CURRENT_ENV_PREFIX` | conda env prefix | `/root/miniconda3/envs/vllm-hust-dev`(本机可能落在 `/data/conda-envs/vllm-hust-main-tf5-backfill/`) |
| `CURRENT_VLLM_HUST_REPO` | vllm-hust 仓路径 | `$WORKSPACE_ROOT/vllm-hust` |
| `CURRENT_VLLM_ASCEND_HUST_REPO` | vllm-ascend-hust 仓路径 | `$WORKSPACE_ROOT/vllm-ascend-hust` |
| `CURRENT_MODEL_PATH` | 模型本地路径 | `/data/shared_models/Qwen--Qwen2.5-14B-Instruct` |
| `CURRENT_SERVER_PORT` | 服务端口 | `8001` |
| `CURRENT_SUBMITTER` | 提交者标识 | `same-spec-current` |
| `CURRENT_ENGINE` | 引擎标识 | `vllm-hust` |

### 最小可运行命令

```bash
cd vllm-hust-benchmark
bash scripts/run-current-ascend-same-spec.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json
```

### 产出目录说明

- raw benchmark 结果:`vllm-hust-benchmark/.benchmarks/current-ascend-same-spec/<run-id>/`
- 导出的 leaderboard artifact:`.../submission/`
- 归档到 leaderboard 时:`vllm-hust-benchmark/submissions/<run-id>/`

## 路径 B 详细:vllm 官方 baseline

### 关键开关

| 开关 | 含义 | 默认 |
|------|------|------|
| `SKIP_OFFICIAL_ASCEND_C_EXTENSION_BUILD=1` | 跳过 fragile 的官方 custom-op 构建,走 sampler fallback | 开 |
| `PREPARE_OFFICIAL_ENV=1` | 跑前自动 prepare/repair pinned env | 开 |
| `FORCE_REPAIR_OFFICIAL_ENV=1` | 强制重装 env | 关 |
| `--repeat-count N` | 每个 missing canonical spec 跑 N 次取中位数 | `1`,推荐 `3` |
| `--review-existing` | 已存在 canonical 的 spec 也重跑一次但不替换 canonical | 关 |
| `--devices 0` 或 `1,2` | 指定 NPU 设备 | 不指定时由脚本决定 |
| `--publish-website` | 跑完本地重建 `vllm-hust-website/data/` | 关 |

### 环境变量(底层 `run-official-ascend-goal-baseline.sh` 读)

| 变量名 | 含义 | 默认值 |
|--------|------|--------|
| `GOAL_BASELINE_ENV_PREFIX` | 官方 pinned env prefix | `$(conda info --base)/envs/vllm-ascend-official-v0180` |
| `OFFICIAL_MODEL_PATH` | 模型本地路径 | `/data/shared_models/Qwen--Qwen2.5-14B-Instruct` |
| `HF_ENDPOINT` | HF 镜像 | `https://hf-mirror.com` |
| `VLLM_CACHE_ROOT` | vLLM 缓存目录 | `.cache/official-ascend-goal-baseline/` |

### 典型命令

全量(跑全部 missing official baseline,每个 3 次取中位数):

```bash
cd vllm-hust-benchmark
bash scripts/run-official-v0180-baselines.sh --repeat-count 3
```

单 spec、单卡:

```bash
cd vllm-hust-benchmark
bash scripts/run-official-v0180-baselines.sh --devices 0 --repeat-count 3 \
  docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json
```

review-existing(对已有 canonical 的 spec 重跑一次但不替换):

```bash
cd vllm-hust-benchmark
bash scripts/run-official-v0180-baselines.sh --review-existing --repeat-count 3
```

### 产出目录说明

- raw benchmark 结果:`vllm-hust-benchmark/.benchmarks/official-ascend-goal-baseline/`
- 导出的 leaderboard artifact:`.../submission/`
- 提升为 canonical 时:`vllm-hust-benchmark/submissions/official-ascend-*`

> `v0.11.0` 已退役,不得重新发布到 `leaderboard-data/snapshots`。

## 路径 C:单卡历史 commit backfill

补 `vllm-hust` 历史 commit 在 910B2 单卡上的缺失 workload。

```bash
python3 scripts/backfill_single_gpu.py run --commit <sha> --workload <name>
```

- 产出:`.benchmarks/backfill-single-gpu/` 与 `submissions/single-gpu-backfill-*`
- 详见 [04-backfill-paths.md](04-backfill-paths.md)

## 路径 D:历史 PR real-online backfill

跑历史 PR 的 real-online benchmark,通过 `manage.sh --managed-dev-hub` 启服务。

```bash
PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file <plan.json> --managed-dev-hub --execute
```

- 产出:`.benchmarks/historical-pr-backfill/` 与 `submissions/historical-pr-*`
- 详见 [04-backfill-paths.md](04-backfill-paths.md)

## 路径 E:组织成员 delta 基准

为组织成员的 commit 跑 benchmark,计算相对上游的 delta。

```bash
GH_TOKEN=<token> python3 scripts/run_org_member_benchmarks.py run --dry-run
```

- 产出:`.benchmarks/checkpoint.json` 与 `submissions/`
- attribution 模型:PR commits → 1 benchmark/PR;consecutive commits(无 PR)→ 1 benchmark/session;delta = `perf(org_group) - perf(previous_upstream_group)`
- 详见 [04-backfill-paths.md](04-backfill-paths.md)

## 路径 F:msprof profiling

同 spec 跑一次 benchmark + msprof 性能剖析。

```bash
bash scripts/run-current-ascend-same-spec-msprof.sh <spec.json>
```

- 产出:`.benchmarks/current-ascend-msprof/<run-id>/`,含 `msprof_raw/` 与 `benchmark/`
- 配置文件:`scripts/run-current-ascend-same-spec-msprof.env`
- 默认 msprof flags:`--ascendcl=on --runtime-api=on --task-time=l1 --hccl=on --type=text`

## 路径 G:campaign 重复跑

同 spec 重复 N 次(默认 3),取中位数。

```bash
bash scripts/run-campaign-repetitions.sh <spec.json> \
  --campaign-prefix <prefix> --repetitions 3
```

- 产出:`submissions/<campaign-prefix>-<workload>-<chip>chip-<ts>/`(N 份独立 artifact 目录)
- 内部调 `run-single-repetition.sh`,每份 artifact 含 `run_leaderboard.json` / `env-manifest.json` / `checksums.sha256` / `STATUS`

## 路径 H:matrix 多 spec 批量跑

一次跑一个目录下所有 spec,内部调路径 A 的 runner。

```bash
bash scripts/run-current-ascend-same-spec-matrix.sh docs/spec-matrix/
```

- 产出:`.benchmarks/<matrix-run-id>/<spec-slug>/`(每 spec 一份)
- 设 `PUBLISH_WEBSITE=1` 可在跑完后聚合到 `vllm-hust-website/data`

## A/B 对比必须固定的变量

做 fork vs baseline 严格 A/B 对比时,以下变量必须保持一致:

- 同一份 spec JSON(从 `docs/official-baselines/*.json` 选)
- 同一个 model path(本地路径要一致)
- 同一个 NPU 设备(用 `--devices` 或 `ASCEND_VISIBLE_DEVICES` 锁定)
- 同一个端口(避免端口竞争)
- 只切换 conda env 与源码 repo(PYTHONPATH)
- 建议固定 `REPEAT_COUNT=3` 取中位数,避免单次抖动

## 路径 A 的案例:manage.sh 冒烟

只做一次小规模冒烟时,不必走 same-spec runner,可以手动起服务再 `vllm bench serve` 直接打。

1. 用 `dev-hub` 仓的 `manage.sh` 起 vllm-hust 服务:

   ```bash
   cp .env.template .env  # 填入 VLLM_HUST_API_KEY
   VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env ./manage.sh start
   ./manage.sh health
   ```

2. 用 `vllm-hust` 仓的 `vllm bench serve` 直接打:

   ```bash
   vllm bench serve \
     --model <served-model-name> \
     --endpoint /v1/completions \
     --dataset-name random \
     --num-prompts 200 \
     --input-len 1024 --output-len 256 \
     --request-rate 1 \
     --port 8000
   ```

3. 这种方式不会自动产出 leaderboard artifact,只适合本地调试,不要把结果直接塞进 `submissions/`。
