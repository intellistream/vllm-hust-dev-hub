# Paul 的 task 分类与代码优化路径

## Paul 实际任务画像

`pr-analysis.md` 把 Paul 标为 "Data Backfill Specialist",但实际任务横跨 5 类:A. Backfill 数据补点、B. Leaderboard 数据完整性、C. CI/CD 与 perfgate(reviewer)、D. Benchmark 脚本与契约、E. 回归调查与性能研究。本文档按这 5 类给出每类的相关 PR/issue、核心脚本、上游依赖、下游消费者、脆弱点。

## A 类:Backfill 数据补点

### 相关 PR/issue

| 类型 | 编号 | 说明 |
|------|------|------|
| Authored PR | #99 | OPEN,118 验证错误阻塞中 |
| Authored PR | #80、#73、#60、#57 | 均为 +13k~14k 行 submission bundle |
| Core issue | benchmark #89 | P0,30 个已合并 PR 的 backfill 实证,预估 17.5 天 |
| Core issue | benchmark #90 | P0,5 个研究方向 16 个 open PR 实验 |

### 核心脚本

| 脚本 | 作用 |
|------|------|
| `scripts/backfill_single_gpu.py` | 单文件 ~3761 行,含 plan/run/fill/status/aggregate/validate/push/restore 8 个子命令 |
| `scripts/backfill_historical_pr_benchmarks.py` | 更高层 driver,包裹 `run-current-ascend-same-spec.sh` |

### 上游依赖

- `vllm-hust` 的 `vllm/benchmarks/`(latency.py、serve.py、startup.py、sweep/cli.py)与 `vllm/benchmarks/lib/endpoint_request_func.py`
- dev-hub `manage.sh --managed-dev-hub`

### 下游消费者

- `submissions/`
- `leaderboard-data/snapshots/`
- HF dataset `intellistream/vllm-hust-benchmark-results`

### 脆弱点

- 单文件 3761 行,plugin 解析、NPU 调度、server 启动、client 运行、artifact 提交混在一起
- PR #80 曾因 monkeypatch 源码被 flag

## B 类:Leaderboard 数据完整性

### 相关 issue

| 编号 | 说明 |
|------|------|
| benchmark #105 | P0,全局清理与重建 |
| benchmark #97 | P0,PR #80 的 prefix-repetition-online 启动故障 |

### 核心脚本

| 脚本 | 作用 |
|------|------|
| `scripts/archive_superseded_coexistence.py` | 归档 superseded 共存记录 |
| `scripts/repair_same_spec_hash.py` | 修复 same-spec hash |
| `scripts/validate_public_leaderboard_snapshots.py` | 校验公开 leaderboard 快照 |

### 数据源

- `archive/suspect/`(4 个 suspect 目标:7a63-main、7fa0e3ed4b、main-2206-instructcoder、single-card-high-ttft-outliers)
- `docs/suspect-historical-targets.md`
- `docs/HISTORICAL_PR_BENCHMARK_BLACKLIST.md`(目前仅 1 条黑名单 `bf2984e34a`)
- `docs/leaderboard-exclusions.json`

### 上游依赖

- `leaderboard-data/snapshots/`
- `archive/suspect/`

### 下游消费者

- `vllm-hust-website/scripts/aggregate_results.py`
- website 仓 mirror

### 脆弱点

- superseded 共存检测靠 `(engine_commit, plugin_commit)` 二级分组,canonical 取 earliest-submitted

## C 类:CI/CD 与 perfgate(reviewer 角色)

### Reviewer PR

| 编号 | 作者 | 主题 |
|------|------|------|
| #69 | Shuhao | perfgate 拒绝非法 central baseline |
| #64 | Shuhao | CI public checkout contract |
| #63 | Shuhao | single-NPU backfill batch |
| #62 | junhuizhang | Ascend same-spec 启动可靠性 |

### 核心模块

- `src/vllm_hust_benchmark/perfgate.py`
- `src/vllm_hust_benchmark/perfgate_baselines.py`
- `src/vllm_hust_benchmark/perfgate_specs.py`

### 上游依赖

- `docs/official-baselines/perfgate-*.json`

### 下游消费者

- `.github/workflows/ci.yml`

### 脆弱点

- perfgate spec 与 official baseline 目录边界易混(`agent.md` 已明示约束)

## D 类:Benchmark 脚本与契约

### 相关 PR

| 类型 | 编号 | 说明 |
|------|------|------|
| Authored PR | #80 | 含 chore 脚本(workload_config_contract、no_stream 参数修复) |
| Reviewer PR | #75 | GuMorming SimLLM,OPEN 待 Paul 审 |
| Reviewer PR | #72 | hustcui KV int8 |

### 核心模块

- `src/vllm_hust_benchmark/workload_config_contract.py`(`validate_explicit_workload_config`)
- `src/vllm_hust_benchmark/submission_artifacts.py`
- `src/vllm_hust_benchmark/same_spec.py`
- `src/vllm_hust_benchmark/integration.py`(`_find_superseded_coexistence_conflicts` + 拒绝报告生成)

### 契约文档

- `docs/LEADERBOARD_ALIGNMENT.md`
- `docs/HISTORICAL_PR_BACKFILL_AGGREGATE_CONTRACT.md`(data_source marker 豁免规则)

### 上游依赖

- `docs/LEADERBOARD_ALIGNMENT.md` schema

### 下游消费者

- `validate_public_leaderboard_snapshots.py`

### 脆弱点

- contract marker `explicit-effective/v1` 是硬门,缺字段即拒

## E 类:回归调查与性能研究

### 相关 issue

| 仓库 | 编号 | 说明 |
|------|------|------|
| core | #58 | Ngram 3x TPOT 回归 |
| core | #146 | 7 月区间回归 |
| core | #151 | 6 个性能跳变 |
| core | #163 | P0,Prefix 78% 吞吐回归 |
| core | #183 | KV Cache 研究 |
| ascend | #145 | P0,两卡 40-47% 回归 |

#### 文档定位

- #58 / #146 / #151 / #163 → 回归 bisect SOP 见 [08-regression-bisect-sop.md](08-regression-bisect-sop.md)
- #183(KV Cache 研究)→ 研究方法论见 [09-multi-chip-and-research.md](09-multi-chip-and-research.md)
- ascend #145(两卡回归)→ 多卡路径与 bisect 见 [09-multi-chip-and-research.md](09-multi-chip-and-research.md)
- output 指标好坏判断见 [10-output-metrics-guide.md](10-output-metrics-guide.md)

### 上游依赖

- `vllm-hust` 的 `vllm/benchmarks/`(latency.py、serve.py、startup.py、sweep/cli.py)
- `vllm/benchmarks/lib/endpoint_request_func.py`
- dev-hub `manage.sh --managed-dev-hub`

### 下游消费者

- benchmark submissions
- leaderboard snapshots
- 回归分析报告(通常在 issue 里讨论,不单独入库)

### 脆弱点

- 回归调查依赖 backfill 工作链(A 类)产出数据
- 性能跳变定位需要 msprof(路径 F)协同

## 代码优化路径总览表

| 类别 | 核心入口 | 上游依赖 | 下游消费者 | 脆弱点 |
|------|----------|----------|------------|--------|
| A. Backfill 数据补点 | `backfill_single_gpu.py` / `backfill_historical_pr_benchmarks.py` | vllm-hust `vllm/benchmarks/` + `manage.sh --managed-dev-hub` | `submissions/`、snapshots、HF dataset | 单文件 3761 行职责混杂,monkeypatch 易被 flag |
| B. Leaderboard 数据完整性 | `archive_superseded_coexistence.py` / `repair_same_spec_hash.py` / `validate_public_leaderboard_snapshots.py` | `leaderboard-data/snapshots/`、`archive/suspect/` | website `aggregate_results.py`、website mirror | superseded 共存靠 `(engine_commit, plugin_commit)` 二级分组,canonical 取 earliest-submitted |
| C. CI/CD 与 perfgate | `perfgate.py` / `perfgate_baselines.py` / `perfgate_specs.py` | `docs/official-baselines/perfgate-*.json` | `.github/workflows/ci.yml` | perfgate spec 与 official baseline 目录边界易混 |
| D. Benchmark 脚本与契约 | `workload_config_contract.py` / `submission_artifacts.py` / `same_spec.py` / `integration.py` | `docs/LEADERBOARD_ALIGNMENT.md` schema | `validate_public_leaderboard_snapshots.py` | contract marker `explicit-effective/v1` 是硬门,缺字段即拒 |
| E. 回归调查与性能研究 | 复用 A 类 backfill 工作链 + vllm-hust benchmarks | vllm-hust `vllm/benchmarks/` + `manage.sh --managed-dev-hub` | submissions、snapshots、issue 内分析报告 | 依赖 A 类数据产出,性能跳变定位需 msprof(路径 F)协同 |
