# submission 与 snapshot 产出体系

- 本文档说明 submission 目录与 snapshot 目录的完整产出体系
- metrics 字段含义见 [10-output-metrics-guide.md](10-output-metrics-guide.md)
- 路径选择见 [02-benchmark-paths.md](02-benchmark-paths.md)

## submission 目录文件清单

| 文件名 | 产出方 | 格式 | 作用 | 关键字段 |
|--------|--------|------|------|----------|
| `STATUS` | `collect-run-artifact.sh` | 纯文本 | 标记本次运行整体状态,供 admission gate 消费 | `OK` 或 `FAILED: <reason>` |
| `checksums.sha256` | `collect-run-artifact.sh` | sha256sum 文本 | 对目录内除自身与 STATUS 外的所有文件计算 SHA256,完整性校验 | 7 行 `<sha256>  ./<filename>` |
| `env-manifest.json` | `collect-run-artifact.sh`(内嵌 Python) | JSON | 运行环境指纹 | `manifest_version`(run-env-manifest/v1)、`collected_at`、`os`、`python_version`、`hostname`、`conda_env`、`ascend_toolkit`、`npu_smi`、`env_vars`、`git_info`(vllm_hust/vllm_ascend_hust/benchmark commit) |
| `leaderboard_manifest.json` | leaderboard exporter | JSON | 声明本 submission 的 artifact 与幂等键,跨仓边界 contract | `schema_version`(leaderboard-export-manifest/v2)、`generated_at`、`entries[]`(`idempotency_key`、`leaderboard_artifact`) |
| `pip-packages.json` | `collect-run-artifact.sh`(`pip list --format=json`) | JSON 数组 | 完整 pip 依赖清单,便于复现 | 每项 `{name, version, [editable_project_location]}` |
| `raw_benchmark_result.json` | vLLM bench runtime | JSON | 原始 benchmark 指标,非跨仓 contract,字段随 vllm 版本变化 | `date`、`endpoint_type`、`backend`、`model_id`、`num_prompts`、`request_rate`、`duration`、`completed`、`failed`、`total_input_tokens`、`total_output_tokens`、`request_throughput`、`output_throughput`、`total_token_throughput`、`mean_ttft_ms`、`median_ttft_ms`、`p99_ttft_ms`、`mean_tpot_ms`、`mean_itl_ms` |
| `resolved_same_spec.json` | `same_spec` resolver | JSON | 锚定可比参数与 spec hash,compare 与 official baseline 校验依赖此文件 | `schema_version`(benchmark-same-spec/v1)、`spec_id`、`spec_label`、`spec_source`、`scenario`、`model`、`model_parameters`、`model_precision`、`hardware_vendor`、`hardware_chip_model`、`chip_count`、`node_count`、`resolved_server_parameters`、`resolved_client_parameters`、`resolved_spec_hash` |
| `run_leaderboard.json` | leaderboard exporter | JSON | 标准 leaderboard 单条 entry,website schema 兼容,聚合器直接消费 | `entry_id`、`engine`、`engine_version`、`config_type`、`hardware`、`model`、`workload`、`metrics`(5 字段)、`constraints`、`metadata`(`submitted_at`/`submitter`/`data_source`/`git_commit`/`idempotency_key`/`runtime_provenance`)、`same_spec` |
| `server.stdout.log` | vLLM server 进程 | 纯文本日志 | vLLM 启动与运行时日志,审计与排障用 | 平台插件激活、模型加载、参数解析等日志行 |

## snapshot 目录文件清单

| 文件名 | 产出方 | 格式 | 作用 | 关键字段 |
|--------|--------|------|------|----------|
| `leaderboard_single.json` | `aggregate_results.py`(website 仓) | JSON 数组 | 单卡(`config_type=single_gpu`)entry 聚合快照,网站第一优先级数据源 | 每项为完整 entry(同 run_leaderboard.json 结构) |
| `leaderboard_multi.json` | `aggregate_results.py`(website 仓) | JSON 数组 | 多卡(`config_type=multi_gpu`)entry 聚合快照 | 同上,`hardware.chip_count`≥2 |
| `leaderboard_compare.json` | `aggregate_results.py`(website 仓) | JSON | compare 视图:同 scope 下不同 engine 的对比组 | `schema_version`(leaderboard-compare-snapshot/v1)、`generated_at`、`group_count`、`preferred_pair_count`、`groups[]`(`scope_key`/`category`/`scope`/`engines[]`) |
| `last_updated.json` | 聚合脚本 | JSON | 网站缓存 marker,标记 snapshot 最新刷新时间 | `last_updated`(ISO 8601 timestamp) |
| `admission_report.json` | `scripts/generate_admission_report.py` | JSON | 每个 snapshot entry 的接纳决策报告,对照 fixed-target registry | `schema_version`(admission-report/v1)、`generated_at`、`registry_version`、`entries[]`(`entry_id`/`scenario`/`actual_config`/`artifact_path`/`profile_name`/`required_config`/`missing_fields`/`drift_fields`/`disposition`/`reason`) |
| `rejected_superseded_report.json` | `aggregate_to_website`(integration.py) | JSON | 聚合过程中被拒/被 superseded/目标失配的 entry 汇总,审计用 | `schema_version`(rejected-superseded-report/v1)、`generated_at`、`rejected_submissions[]`、`superseded_entries[]`(`old_entry_id`/`new_entry_id`/`supersedes_reason`/`archive_path`)、`excluded_plugin_commits[]`、`target_misaligned_entries[]` |
| `pre_cleanup_freeze.json` | cleanup 流程前的冻结脚本 | JSON | cleanup 前的冻结快照,记录当时 single/multi 的 checksum 与全部 entry_id,用于回滚与审计 | `schema_version`(freeze-snapshot/v1)、`frozen_at`、`leaderboard_single_checksum`、`leaderboard_multi_checksum`、`entry_ids[]`、`source_commit` |

## submission→snapshot 派生流程

入口命令:

```
python -m vllm_hust_benchmark.cli publish-website \
  --source-dir submissions \
  --output-dir leaderboard-data/snapshots \
  --execute
```

```
submissions/<run-id>/ (含 STATUS, checksums, run_leaderboard.json, manifest 等)
        │
        ▼
[gate 1] 加载 public leaderboard exclusions
        → 若有 excluded 目录,写 rejected_superseded_report 并退出
        │
        ▼
[gate 2] (可选) 校验 formal submission source(pr-preview 过滤)
        │
        ▼
[gate 3] _scan_submission_admission_failures
        → STATUS 非 OK / artifact 缺失 → 写报告退出
        │
        ▼
[gate 4] _find_superseded_coexistence_conflicts
        → 同 signature+code_combo 且未 supersedes → 写报告退出
        │
        ▼
调用 vllm-hust-website/scripts/aggregate_results.py
        (按 idempotency_key 去重,按 config_type 分流到 single/multi,
         按 same_spec.scope_key 构建 compare groups)
        │
        ▼
[post] fixed-target admission gate: _scan_fixed_target_misaligned_entries
        → 失配 entry 从 official snapshot 隔离(quarantine)
        │
        ▼
_build_rejected_superseded_report(含 target_misaligned_entries)
        │
        ▼
leaderboard_single.json / leaderboard_multi.json / leaderboard_compare.json / last_updated.json
```

- 聚合器扫描 `--source-dir` 下每个子目录,每个子目录须含 `run_leaderboard.json`
- 去重规则:`idempotency_key`(由 `scenario+engine+engine_version+model_identity+chip_model+chip_count+node_count+run_id` 的 SHA-256 生成)
- superseded 共存规则:先按 `build_series_signature` 主分组,再按 `(engine_commit, plugin_commit)` 二次分组;同组内按 `submitted_at` 排序,最新者为 "new",旧者若未被 `metadata.supersedes` 引用则记为冲突
- snapshot 更新触发时机:`publish-website` 手动触发、`sync-submission-to-hf` workflow 触发、`push-to-hf.yml` 监听 `submissions/**` 变化触发

## 三类报告含义

| 报告 | 产出方 | 作用 | 关键字段 | disposition 取值 |
|------|--------|------|----------|-----------------|
| `admission_report.json` | `generate_admission_report.py` | 逐条 entry 对照 fixed-target registry 给接纳决策 | `entries[]`(`entry_id`/`scenario`/`actual_config`/`required_config`/`missing_fields`/`drift_fields`/`disposition`/`reason`) | `keep`(匹配 profile 或非官方 entry)、`quarantine`(missing_fields 或 drift_fields)、`specialty`(specialty target 无固定 contract)、`rerun` |
| `rejected_superseded_report.json` | `aggregate_to_website`(integration.py) | 聚合过程中被拒/被 superseded/目标失配汇总 | `rejected_submissions[]`、`superseded_entries[]`(`old_entry_id`/`new_entry_id`/`supersedes_reason`/`archive_path`)、`excluded_plugin_commits[]`、`target_misaligned_entries[]`(`entry_id`/`snapshot_file`/`profile_name`/`reason`/`detail`/`disposition`) | `quarantine`、`specialty` |
| `pre_cleanup_freeze.json` | cleanup 前的冻结脚本 | cleanup 前的不可变审计点,便于回滚 | `frozen_at`、`leaderboard_single_checksum`、`leaderboard_multi_checksum`、`entry_ids[]`、`source_commit` | (无 disposition,是冻结点) |

排查指引:

- entry 没进 snapshot → 先看 `rejected_superseded_report.json` 的 `rejected_submissions`(STATUS 非 OK 或 artifact 缺失)
- entry 被标记 superseded → 看 `superseded_entries` 的 `supersedes_reason` 与 `archive_path`
- entry 进了 snapshot 但被隔离 → 看 `target_misaligned_entries` 的 `reason`(`missing_gpu_memory_utilization`/`missing_max_model_len`/`config_drift`)

## leaderboard_compare.json 结构

- 不是 single + multi 的简单合并,是独立的对比视图聚合产物
- 顶层:`schema_version`(leaderboard-compare-snapshot/v1)、`generated_at`、`group_count`、`preferred_pair_count`、`groups[]`
- 每个 group 表示一个对比 scope:
  - `scope_key`:管道分隔的 scope 标识(如 `hf:Qwen/Qwen2.5-14B-Instruct|910B2|FP16|...`)
  - `category`:`single` 或 `multi`(对应来源 snapshot 文件)
  - `scope`:`model`/`hardware`/`precision`/`workload`/`config_type`/`chip_count`/`setting_signature`/`setting_summary`
  - `engines[]`:同 scope 下各 engine 的 entry,含 `engine`/`engine_version`/`entry_id`/`submitted_at`/`same_spec`/`metrics`/`constraints`
- 作用:在前端展示 `vllm` vs `vllm-hust` 同 scope 对比

## artifact 校验流程

### collect-run-artifact.sh(运行后收集,4 步)

1. 内嵌 Python 生成 `env-manifest.json`(OS/Python/hostname/conda_env/ascend_toolkit/npu_smi/env_vars/git_info)
2. `pip list --format=json` 生成 `pip-packages.json`
3. `find . -type f ! -name checksums.sha256 ! -name STATUS -exec sha256sum {} \;` 生成 `checksums.sha256`
4. 写 `STATUS`(`OK` 或 `FAILED: <reason>`)

### validate-run-artifact.sh(6 项校验)

1. STATUS 存在且为 `OK`
2. `run_leaderboard.json` 存在且为合法 JSON
3. `leaderboard_manifest.json` 存在、合法 JSON,且 `entries[0].leaderboard_artifact` 引用 `run_leaderboard.json`
4. `env-manifest.json` 存在、合法 JSON,含 `os`/`python_version`/`collected_at`
5. `checksums.sha256` 存在且 `sha256sum -c` 全部通过
6. `run_leaderboard.json` 通过 `submission_artifacts.normalize_submission_artifact_contract` 契约校验

### checksums.sha256 校验范围

覆盖 7 个文件:`raw_benchmark_result.json`、`leaderboard_manifest.json`、`server.stdout.log`、`env-manifest.json`、`resolved_same_spec.json`、`run_leaderboard.json`、`pip-packages.json`。排除自身与 STATUS。任一文件改动即校验失败,需重跑 `collect-run-artifact.sh`。

## submission 目录命名规则

以 `codex-latest-main-tf5-prefix-prefix-repetition-online-1chip-20260726T075441Z` 为例,各段含义:

| 段 | 含义 | 示例 |
|----|------|------|
| 1 | 提交源/运行发起方 | `codex` |
| 2 | 分支/环境标识 | `latest-main-tf5` |
| 3 | 场景前缀标记 | `prefix` |
| 4 | workload/scenario 名称(与 `same_spec.scenario` 一致) | `prefix-repetition-online` |
| 5 | 芯片数量(与 `hardware.chip_count` 对应) | `1chip` |
| 6 | ISO 8601 时间戳(`YYYYMMDDTHHMMSSZ`,UTC) | `20260726T075441Z` |

注:该命名仅为人类可读标签,所有权威字段(芯片数、场景、提交时间)以 `run_leaderboard.json` 内的 `hardware.chip_count`、`workload.name`、`metadata.submitted_at` 为准;`validate_public_leaderboard_snapshots.py` 明确禁止从文件名推断 `910B2`/`FP16` 等标签。
