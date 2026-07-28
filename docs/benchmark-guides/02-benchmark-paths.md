# 手动 Benchmark 路径对比

workspace 的手动 benchmark 有两条互斥路径,都跑 `vllm-hust-benchmark` 仓里的脚本,都吃同一份 spec JSON,但目标、conda env、源码位置、产出目录完全不同。一句话:`vllm-hust 执行版走 same-spec runner,vllm 官方 baseline 走 official-v0180-baselines runner`。

## 两条路径对照表

| 维度 | 路径 A:vllm-hust 执行版 | 路径 B:vllm 官方 baseline |
|------|------------------------|--------------------------|
| 目标 | 测当前 `vllm-hust` 主干 + `vllm-ascend-hust` 主干在 Ascend 910B2 上的性能 | 建立或复核官方 vLLM v0.18.0 + vLLM-Ascend v0.18.0 pinned baseline |
| 入口脚本 | `vllm-hust-benchmark/scripts/run-current-ascend-same-spec.sh` | `vllm-hust-benchmark/scripts/run-official-v0180-baselines.sh` |
| conda env 名 | `vllm-hust-dev` | `vllm-ascend-official-v0180` |
| 源码位置 | `$WORKSPACE_ROOT/vllm-hust` + `$WORKSPACE_ROOT/vllm-ascend-hust` | `reference-repos/vllm@v0.18.0` + `reference-repos/vllm-ascend@v0.18.0` worktree |
| PYTHONPATH 注入方式 | `$CURRENT_VLLM_ASCEND_HUST_REPO:$CURRENT_VLLM_HUST_REPO` 注入 | 官方 worktree 路径注入 |
| 是否安装到 site-packages | 否,通过 PYTHONPATH | 否,通过 PYTHONPATH |
| 默认 NPU 设备选择 | 由 same-spec runner 内部决定 | `--devices` 指定,如 `0` 或 `1,2` |
| raw 产出目录 | `vllm-hust-benchmark/.benchmarks/current-ascend-same-spec/<run-id>/` | `vllm-hust-benchmark/.benchmarks/official-ascend-goal-baseline/` |
| leaderboard 归档目录 | `vllm-hust-benchmark/submissions/<run-id>/` | `vllm-hust-benchmark/submissions/official-ascend-*` |
| 典型命令(一行) | `bash scripts/run-current-ascend-same-spec.sh docs/official-baselines/<spec>.json` | `bash scripts/run-official-v0180-baselines.sh --repeat-count 3` |
| 典型用途 | 验证 fork 优化、回归测试、给 leaderboard 贡献 vllm-hust 一侧数据 | 建立官方 baseline、复核已有 baseline、给 leaderboard 提供 vllm 一侧对照数据 |

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

## A/B 对比必须固定的变量

做 fork vs baseline 严格 A/B 对比时,以下变量必须保持一致:

- 同一份 spec JSON(从 `docs/official-baselines/*.json` 选)
- 同一个 model path(本地路径要一致)
- 同一个 NPU 设备(用 `--devices` 或 `ASCEND_VISIBLE_DEVICES` 锁定)
- 同一个端口(避免端口竞争)
- 只切换 conda env 与源码 repo(PYTHONPATH)
- 建议固定 `REPEAT_COUNT=3` 取中位数,避免单次抖动

## manage.sh 冒烟变体

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
