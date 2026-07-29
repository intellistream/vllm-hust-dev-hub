# FAQ 与 issue 映射速查

新人遇到具体问题时,先按"症状"在下表定位,再点链接深入。每条只给一行解决方案 hint + 指向的文档/脚本。文档总览见 [INDEX.md](INDEX.md)。

## 五大场景入口

| 场景 | 你想做什么 | 主入口 |
|------|-----------|--------|
| 手动跑 | 跑一次 benchmark(单 spec / 冒烟 / 重复 / 多 spec / msprof) | [02-benchmark-paths.md](02-benchmark-paths.md) |
| 自动跑 | 触发 CI / 官方 baseline workflow / HF 同步 | 本文 §自动路径 |
| 校验 | 本地 CI / 单 artifact / snapshot / 跨仓一致性 / trend / admission | 本文 §校验路径 |
| 排查 | website 不刷新 / entry 没进榜 / 性能回归 / 服务起不来 | 本文 §排障路径 |
| 补数据 | 历史 PR / 单卡 backfill | [04-backfill-paths.md](04-backfill-paths.md) |

## 手动路径速查

| 症状 / 需求 | 用哪条路径 | 一行 hint |
|------------|-----------|----------|
| 第一次跑,验证环境 | [00 冒烟](00-quickstart.md) | `VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env bash manage.sh start` |
| 跑 vllm-hust 执行版单 spec | [02 路径 A](02-benchmark-paths.md) | `bash scripts/run-current-ascend-same-spec.sh <spec.json>` |
| 跑 vllm 官方 v0.18.0 baseline | [02 路径 B](02-benchmark-paths.md) | `bash scripts/run-official-v0180-baselines.sh --repeat-count 3` |
| 同 spec 重复 N 次取中位数 | [02 路径 G](02-benchmark-paths.md) | `bash scripts/run-campaign-repetitions.sh <spec> --repetitions 3` |
| 一次跑多个 spec | [02 路径 H](02-benchmark-paths.md) | `bash scripts/run-current-ascend-same-spec-matrix.sh docs/spec-matrix/` |
| 采 msprof 性能剖析 | [02 路径 F](02-benchmark-paths.md) | `bash scripts/run-current-ascend-same-spec-msprof.sh <spec.json>` |
| 补历史 PR 数据 | [04 路径 D](04-backfill-paths.md) | `python scripts/backfill_historical_pr_benchmarks.py --plan-file <plan.json> --managed-dev-hub --execute` |
| 补单卡缺失 workload | [04 路径 C](04-backfill-paths.md) | `python3 scripts/backfill_single_gpu.py run --commit <sha> --workload <name>` |

## 自动路径速查

| 触发场景 | workflow / 脚本 | 触发方式 | 产出 |
|---------|----------------|---------|------|
| 提 PR / push main | `.github/workflows/ci.yml` | 自动 | pytest + pre-commit + trend 校验 |
| 跑官方 baseline 矩阵 | `.github/workflows/run-official-ascend-baselines.yml` | 手动 `gh workflow run` | `submissions/official-ascend-*` + snapshot 刷新 |
| push 到 `leaderboard-data/snapshots/**` | `.github/workflows/notify-website-leaderboard.yml` | 自动 | 向 website 仓发 dispatch |
| 同步 submissions 到 HF | `.github/workflows/push-to-hf.yml` | 自动 / 手动 `workflow_dispatch` | HF dataset `intellistream/vllm-hust-benchmark-results` |

手动触发官方 baseline workflow:

```bash
gh workflow run run-official-ascend-baselines.yml \
  -f repeat-count=3 -f devices=0
```

## 校验路径速查

| 校验目标 | 脚本 | 何时跑 | 失败表现 |
|---------|------|--------|---------|
| 本地 CI 平价 | `scripts/validate-local.sh` | push 前 | pre-commit / pytest 报错 |
| 单 artifact 6 项 | `scripts/validate-run-artifact.sh <artifact-dir>` | 每次跑完 | STATUS 非 OK / checksum 不过 |
| 公开 snapshot 挡 retired | `scripts/validate_public_leaderboard_snapshots.py` | snapshot 更新前 | 混入 v0.11.0 / BF16 / 910B3 |
| 跨仓 checksum 一致 | `scripts/validate_snapshot_consistency.py` | HF 同步后 | GitHub 与 HF snapshot 不一致 |
| trend entry schema | `scripts/validate_trend_entries.py` | CI 内自动 | trend JSON 不合规 |
| admission 接纳决策 | `scripts/generate_admission_report.py` | snapshot 聚合后 | entry 被 quarantine |
| artifact 校验流程详解 | [11 §artifact 校验](11-submission-snapshot-output.md) | — | — |

## 排障路径速查

| 症状 | 第一步看哪 | 详情 |
|------|-----------|------|
| 服务起不来 / port 占用 | [00 常见 3 错](00-quickstart.md) | `lsof -i:18166` 找占用 |
| entry 没进 snapshot | `rejected_superseded_report.json` | [11 §三类报告](11-submission-snapshot-output.md) |
| entry 被标记 superseded | 同上 `superseded_entries[]` | 看 `supersedes_reason` |
| entry 进了但被隔离 | 同上 `target_misaligned_entries[]` | 看 `reason`(`missing_*` / `config_drift`) |
| website 没刷新 | 先看 GitHub snapshot,再看 HF workflow | [11 §派生流程](11-submission-snapshot-output.md) |
| 性能回归(TTFT/TPOT 翻倍) | 多 commit 的 `run_leaderboard.json` 串联 | [08 二分 SOP](08-regression-bisect-sop.md) |
| 单卡 TTFT 异常偏高 | `archive/suspect/single-card-high-ttft-outliers` | [08](08-regression-bisect-sop.md) + `docs/single-card-high-ttft-outlier-audit-*.md` |
| prefix cache 数据可疑 | `docs/prefix-repetition-prefix-cache-audit-*.md` | [09](09-multi-chip-and-research.md) |
| 多卡回归 | 同 spec 多卡 vs 单卡对比 | [09 多卡](09-multi-chip-and-research.md) |
| 看不懂 output 指标 | `run_leaderboard.json` 的 `metrics` 5 字段 | [10 指标解读](10-output-metrics-guide.md) |

## issue → 文档映射

issue 列表见 vllm-hust-benchmark 仓库。常见 issue 对应的文档入口:

| issue | 主题 | 文档入口 |
|-------|------|---------|
| #95 | PR 合并前强制性能证据(merge gate) | `.trae/documents/issue_95_需求分析.md` + `docs/issue_95_layer1_验证方案.md`(CI 集成 Layer 2/3 待 #103) |
| #97 | prefix-repetition-online 启动故障 | [06 遗漏 #2](06-benchmark-gaps-checklist.md)(P0) |
| #99 | backfill 数据验证阻塞 | [06 遗漏 #1](06-benchmark-gaps-checklist.md)(P0) |
| #101 | leaderboard 数据缺口关闭 | [11](11-submission-snapshot-output.md) + [04](04-backfill-paths.md) |
| #102 | Sonnet 清洗复测 | [11 §三类报告](11-submission-snapshot-output.md) |
| #103 | self-hosted Ascend runner 修复 | [02 路径 B](02-benchmark-paths.md) + `docs/LEADERBOARD_HANDOFF.md` §9.3 |
| #104 | fixed-target registry | [11 §admission](11-submission-snapshot-output.md) |
| #105 | 清洗不符合固定靶的性能点 | [11 §三类报告](11-submission-snapshot-output.md) + `.trae/documents/issue_105_需求分析.md` |
| #111 | fixed-target admission dry-run | `docs/issue_105_benchmark_design.md` + `.trae/documents/pr111_需求分析.md` |
| #146 / #151 / #163 | 性能回归跳变 | [08 SOP](08-regression-bisect-sop.md) |
| #145 | 多卡回归 | [09 多卡](09-multi-chip-and-research.md) |

## 新人快速决策树

```
我刚加入 → [00-quickstart] 跑冒烟
   │
   ├─ 跑通了,要跑正式 benchmark → [02-benchmark-paths] 选路径
   │     ├─ 单 spec → 路径 A
   │     ├─ 官方 baseline → 路径 B
   │     ├─ 重复 N 次 → 路径 G
   │     └─ 批量 → 路径 H
   │
   ├─ 要补历史数据 → [04-backfill-paths]
   │
   ├─ 跑完了看结果 → [10-output-metrics-guide] 看指标
   │     └─ entry 没进网站 → [11-submission-snapshot-output] 看报告
   │
   ├─ 性能回归了 → [08-regression-bisect-sop] 二分定位
   │
   ├─ 多卡 / 研究 → [09-multi-chip-and-research]
   │
   ├─ 查参数 → [07-params-cheatsheet]
   │
   └─ 找不到入口 → 本文 FAQ
```

## 仍缺文档的场景(已知缺口)

下列场景现有 docs 未完全覆盖,遇到时去 vllm-hust-benchmark 仓的对应脚本头 docstring 或 `.trae/documents/` 查:

- `run_latest_benchmark.sh` 一键三场景(脚本写死 `/root/miniconda3/...`,新人不可直接跑)
- `repair_same_spec_hash.py` same-spec hash 原子修复
- `archive_superseded_coexistence.py` superseded 归档 runbook
- `leaderboard-exclusions.json` 匹配规则与 fail-closed 防护
- #95 merge gate 的 CI 集成(Layer 2/3 待 #103 runner 就绪)

这些缺口已在 [06-benchmark-gaps-checklist.md](06-benchmark-gaps-checklist.md) 跟踪,本文不重复。
