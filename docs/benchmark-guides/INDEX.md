# Benchmark Guides 索引

本目录共 13 篇文档,覆盖从跑第一条 benchmark 到产出 leaderboard snapshot 的全链路,含 FAQ 与 issue 映射。先看下表选文档,再按角色路径顺序读。

## 13 篇文档定位表

| 编号 | 文档 | 一句话定位 |
|------|------|-----------|
| 00 | [00-quickstart.md](00-quickstart.md) | 新人 5 分钟跑通路径 A 冒烟,验证环境可用 |
| 01 | [01-project-overview.md](01-project-overview.md) | workspace 多仓结构与各 folder 职责,谁负责什么 |
| 02 | [02-benchmark-paths.md](02-benchmark-paths.md) | 8 条 benchmark 路径(A-H)横向对比,选哪条跑 |
| 03 | [03-params-outputs-reference.md](03-params-outputs-reference.md) | spec JSON 三层输入与 run_leaderboard.json 两层输出字段对照 |
| 04 | [04-backfill-paths.md](04-backfill-paths.md) | backfill 两条路径(historical PR / single gpu)与 same-spec runner 的关系 |
| 05 | [05-tasks-and-optimization.md](05-tasks-and-optimization.md) | Paul 的 5 类任务(Backfill/Leaderboard/CI/脚本/回归)分类与代码优化路径 |
| 06 | [06-benchmark-gaps-checklist.md](06-benchmark-gaps-checklist.md) | 脚本与工作流里"真遗漏"的功能 checklist,带优先级 |
| 07 | [07-params-cheatsheet.md](07-params-cheatsheet.md) | 路径 vs 案例速查表 + 关键参数一行解释 |
| 08 | [08-regression-bisect-sop.md](08-regression-bisect-sop.md) | 单卡性能回归二分定位 SOP,覆盖 #58/#146/#151/#163 |
| 09 | [09-multi-chip-and-research.md](09-multi-chip-and-research.md) | 多卡(≥2)benchmark 路径与 KV cache/prefix 等研究方法论 |
| 10 | [10-output-metrics-guide.md](10-output-metrics-guide.md) | metrics 5 字段 + constraints.metrics 16 字段含义、好坏判定,及性能分析分层指引(看哪个文件/哪些指标/按角色) |
| 11 | [11-submission-snapshot-output.md](11-submission-snapshot-output.md) | submission 目录 9 文件 + snapshot 目录 7 文件清单与派生流程 |
| 12 | [12-faq-issue-mapping.md](12-faq-issue-mapping.md) | 五大场景(手动/自动/校验/排障/补数据)FAQ 速查 + issue → 文档映射 |

## 三种角色阅读路径

### 新人(第一次接触 benchmark)

1. [00-quickstart.md](00-quickstart.md) — 跑通冒烟,确认环境
2. [01-project-overview.md](01-project-overview.md) — 搞清楚 4 个仓的职责
3. [02-benchmark-paths.md](02-benchmark-paths.md) — 选一条正式路径
4. [10-output-metrics-guide.md](10-output-metrics-guide.md) — 看懂输出的 5 个核心指标
5. [07-params-cheatsheet.md](07-params-cheatsheet.md) — 查参数时回来翻

### 熟手(已经跑过,要补数据或排查)

1. [02-benchmark-paths.md](02-benchmark-paths.md) — 确认走哪条路径
2. [04-backfill-paths.md](04-backfill-paths.md) — 若是补历史 PR 数据走这里
3. [11-submission-snapshot-output.md](11-submission-snapshot-output.md) — 排查"entry 没进 snapshot"或"被 superseded"
4. (按需)[08-regression-bisect-sop.md](08-regression-bisect-sop.md) — 性能回归时

### 自动 / 校验 / 排障路径

1. [12-faq-issue-mapping.md](12-faq-issue-mapping.md) — 先按症状定位
2. 按表跳到对应的脚本或文档(11 排查报告 / 08 回归 / 09 多卡 / 10 指标)

### Paul(按任务类别)

| 任务类别 | 主入口 | 辅助 |
|---------|--------|------|
| A. Backfill 数据补点 | [04-backfill-paths.md](04-backfill-paths.md) | [11-submission-snapshot-output.md](11-submission-snapshot-output.md) |
| B. Leaderboard 数据完整性 | [11-submission-snapshot-output.md](11-submission-snapshot-output.md) | [10-output-metrics-guide.md](10-output-metrics-guide.md) |
| C. CI/CD 与 perfgate(reviewer) | [06-benchmark-gaps-checklist.md](06-benchmark-gaps-checklist.md) | [03-params-outputs-reference.md](03-params-outputs-reference.md) |
| D. Benchmark 脚本与契约 | [03-params-outputs-reference.md](03-params-outputs-reference.md) | [07-params-cheatsheet.md](07-params-cheatsheet.md) |
| E. 回归调查与性能研究 | [08-regression-bisect-sop.md](08-regression-bisect-sop.md) | [09-multi-chip-and-research.md](09-multi-chip-and-research.md) |

## 文档间依赖关系图

```
                      [01-project-overview]   ← 入门必读
                                │
                                ▼
                      [00-quickstart]   ← 5 分钟冒烟
                                │
                                ▼
                      [02-benchmark-paths]   ← 选路径(A-H)
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   [03-params-outputs]   [04-backfill-paths]   [07-params-cheatsheet]
          │                     │                     ▲
          ▼                     ▼                     │
   [10-output-metrics]   [11-submission-snapshot]    │
          │                     │                     │
          └──────────┬──────────┘                     │
                     ▼                                │
              [05-tasks-and-optimization] ────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
   [08-regression-bisect]  [09-multi-chip-research]
          │                     │
          └──────────┬──────────┘
                     ▼
              [06-benchmark-gaps-checklist]   ← 横向查漏
                     ▲
                     │
   [12-faq-issue-mapping] ── 横向速查,串起所有文档 + issue 编号
```

说明:

- 01、00 是入门,所有人先读
- 02 是分叉点,选路径后看对应的 03/04/07
- 10 与 11 是产出侧两兄弟:10 讲指标含义,11 讲产出体系,互相引用
- 05 是 Paul 任务地图,横向串起 A/B/C/D/E 五类
- 08/09 是深度专题,有具体回归/研究需求时再看
- 06 是横向 checklist,任何角色都可用于查漏
- 12 是横向 FAQ,遇到具体问题/issue 时按症状反查所有文档
