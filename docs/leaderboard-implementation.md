# vllm-hust Leader Board 实现梳理

> **更新日期：** 2026-04-28
> **范围：** `vllm-hust-website` + `vllm-hust-benchmark`（数据生产侧）

---

## 目录

1. [整体架构与仓库地图](#1-整体架构与仓库地图)
2. [端到端数据流](#2-端到端数据流)
3. [数据模型](#3-数据模型)
4. [业务处理逻辑](#4-业务处理逻辑)
   - 4.1 [Benchmark 侧导出（leaderboard_export.py）](#41-benchmark-侧导出-leaderboard_exportpy)
   - 4.2 [聚合脚本（aggregate_results.py）](#42-聚合脚本-aggregate_resultspy)
   - 4.3 [比较快照（Compare Snapshot）](#43-比较快照-compare-snapshot)
   - 4.4 [硬约束评估（Hard Constraints）](#44-硬约束评估-hard-constraints)
   - 4.5 [HuggingFace 发布（hf_publisher.py）](#45-huggingface-发布-hf_publisherpy)
   - 4.6 [前端渲染（index.html）](#46-前端渲染-indexhtml)
5. [CI/CD 流水线](#5-cicd-流水线)
6. [当前数据状态](#6-当前数据状态)
7. [存在的问题](#7-存在的问题)
8. [优化方向](#8-优化方向)

---

## 1. 整体架构与仓库地图

Leader Board 功能跨越以下三个仓库：

| 仓库 | 职责 |
|------|------|
| [`vllm-hust-benchmark`](https://github.com/vLLM-HUST/vllm-hust-benchmark) | 基准测试执行，生成标准导出物（leaderboard artifact + manifest） |
| [`vllm-hust-website`](https://github.com/vLLM-HUST/vllm-hust-website) | 聚合、展示 Leader Board；包含聚合脚本、JSON Schema、快照数据 |
| HuggingFace Dataset（外部） | 主分发层，存储 `leaderboard_single/multi/compare.json` 快照 |

```
┌─────────────────────────────────────────────────────────────────┐
│                        vllm-hust-benchmark                      │
│  vllm bench serve                                               │
│        ↓                                                        │
│  leaderboard_export.py                                          │
│        ↓  (标准导出物)                                          │
│  *_leaderboard.json  +  leaderboard_manifest.json               │
└──────────────┬──────────────────────────────────────────────────┘
               │  主路径：upload-hf           │  离线路径：sync_results_to_website.sh
               ▼                              ▼
   ┌─────────────────────┐      ┌────────────────────────────────┐
   │  HuggingFace Dataset │      │  vllm-hust-website/scripts/    │
   │  leaderboard_*.json │      │  aggregate_results.py          │
   └──────────┬──────────┘      └─────────────┬──────────────────┘
              │  website 拉取                  │  写入 data/
              ▼                               ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                    vllm-hust-website/                        │
   │   data/leaderboard_single.json                              │
   │   data/leaderboard_multi.json                               │
   │   data/leaderboard_compare.json                             │
   │   data/last_updated.json                                    │
   │         ↓                                                    │
   │   index.html  (JavaScript 渲染)                              │
   └──────────────────────────────────────────────────────────────┘
```

---

## 2. 端到端数据流

```
[研究人员 / CI]
     │
     │  1. 执行 benchmark
     ▼
vllm bench serve --workload sharegpt-online \
                 --model Qwen2.5-7B-Instruct \
                 --backend ascend \
                 --hardware 910B2
     │
     │  2. 生成原始结果（JSON）
     ▼
benchmark_result.json  [+]  constraints_metrics.json
     │
     │  3. 调用 leaderboard_export.py（或 vllm bench export / publish）
     ▼
┌─────────────────────────────────────────────────┐
│  *_leaderboard.json  ←  标准单条 artifact        │
│  leaderboard_manifest.json  ←  索引文件          │
│  （schema: leaderboard-export-manifest/v1|v2）   │
└─────────────────────────────────────────────────┘
     │
     │  4a. 主路径（HF 发布）
     ▼
vllm bench upload-hf
     │  → 调用 hf_publisher.py
     │  → 上传 leaderboard_*.json 至 HuggingFace Dataset
     │
     │  4b. 离线路径（本地 website 同步）
     ▼
bash sync_results_to_website.sh
  → python scripts/aggregate_results.py \
      --source-dir <benchmark_outputs> \
      --output-dir data/
     │
     │  5. 聚合处理（aggregate_results.py）
     ▼
①  加载所有 leaderboard_manifest.json
②  递归找到并加载 *_leaderboard.json
③  JSON Schema 验证（leaderboard_v1.schema.json）
④  幂等性去重（by metadata.idempotency_key）
⑤  拆分 single（node_count=1）/ multi（node_count>1）
⑥  生成 Compare Snapshot（compare group + preferred_pair）
⑦  生成 Hard Constraints Snapshot（4 项硬性指标评估）
⑧  写出：
      data/leaderboard_single.json
      data/leaderboard_multi.json
      data/leaderboard_compare.json
      data/last_updated.json
     │
     │  6. 网站前端读取
     ▼
index.html（JavaScript）
  ← fetch leaderboard_single.json
  ← fetch leaderboard_multi.json
  ← fetch leaderboard_compare.json
     │
     │  7. 渲染 Leader Board
     ▼
"Performance Leaderboard" 板块
  - Quick View（单机/多机 Tab）
  - 过滤（芯片型号 / 模型 / 精度 / 负载）
  - Compare 卡（vllm-hust vs baseline）
  - Hard Constraints 状态
```

---

## 3. 数据模型

### 3.1 单条 Leaderboard Entry（leaderboard_v1.schema.json）

```
leaderboard entry
├── entry_id            : UUID
├── engine              : string  (e.g. "vllm-ascend", "vllm-hust")
├── engine_version      : string
├── config_type         : "single_gpu" | "multi_gpu" | "multi_node"
│
├── hardware
│   ├── vendor          : "NVIDIA" | "Huawei" | "Intel/AMD" | ...
│   ├── chip_model      : string  (e.g. "910B2", "A100-80GB")
│   ├── chip_count      : int     (总卡数)
│   └── interconnect    : string  (或 intra_node_interconnect)
│
├── model
│   ├── name            : string
│   ├── parameters      : string  (e.g. "7B")
│   ├── precision       : "FP16" | "BF16" | "INT8" | ...
│   └── quantization    : string | null
│
├── workload
│   ├── name            : string  (e.g. "sharegpt-online")
│   ├── input_length    : int
│   ├── output_length   : int
│   ├── batch_size      : int | null
│   ├── concurrent_requests : int | null
│   └── dataset         : string | null
│
├── metrics             ← 核心性能指标
│   ├── ttft_ms         : float   (Time To First Token，毫秒，必填)
│   ├── throughput_tps  : float   (吞吐量 token/s，必填)
│   ├── peak_mem_mb     : float   (峰值显存 MB，必填)
│   ├── error_rate      : float   (错误率 [0,1]，必填)
│   ├── tbt_ms          : float   (Time Between Tokens，可选)
│   ├── tpot_ms         : float   (Time Per Output Token，可选)
│   ├── prefix_hit_rate : float   (KV 前缀命中率，可选)
│   ├── kv_used_tokens  : int     (KV Cache 已用 token 数，可选)
│   ├── kv_used_bytes   : int     (KV Cache 已用字节，可选)
│   ├── evict_count     : int     (KV 驱逐次数，可选)
│   └── evict_ms        : float   (KV 驱逐耗时，可选)
│
├── constraints         ← 硬约束评估上下文
│   ├── scenario_source : "vllm-benchmark"（固定值）
│   ├── accountable_scope
│   │   ├── domestic_chip_class            : string  (e.g. "Ascend-class")
│   │   ├── representative_model_band      : "7B-13B"
│   │   ├── representative_business_scenario : string
│   │   ├── baseline_engine                : string  (e.g. "vllm")
│   │   └── owner_confirmed                : bool | null
│   └── metrics         ← 硬约束指标（须全部提供）
│       ├── single_chip_effective_utilization_pct
│       ├── typical_throughput_ratio_vs_baseline
│       ├── typical_ttft_reduction_pct_vs_baseline
│       ├── typical_tpot_reduction_pct_vs_baseline
│       ├── long_context_length
│       ├── long_context_throughput_stable
│       ├── long_context_ttft_p95_ms / _p99_ms
│       ├── long_context_tpot_p95_ms / _p99_ms
│       ├── long_context_ttft_p95_stable / _p99_stable
│       ├── long_context_tpot_p95_stable / _p99_stable
│       ├── unit_token_cost_reduction_pct
│       └── multi_tenant_high_utilization
│
├── cluster             : null（单机）| 对象（多机）
│   ├── node_count      : int ≥ 2
│   ├── comm_backend    : string
│   └── topology_type   : string
│
├── versions
│   ├── protocol        : string（必填）
│   ├── backend         : string（必填）
│   ├── core            : string（必填）
│   └── benchmark       : string（可选）
│
├── environment
│   ├── os, python_version, pytorch_version
│   ├── cuda_version, cann_version, driver_version
│   └── ...
│
└── metadata
    ├── submitted_at    : ISO 8601 时间戳
    ├── submitter       : string
    ├── data_source     : string
    ├── reproducible_cmd : string | null
    ├── git_commit      : string | null
    ├── idempotency_key : SHA-256 哈希（唯一性保证）
    └── manifest_source : string
```

### 3.2 leaderboard_compare.json（派生快照）

```
compare snapshot
├── schema_version      : "leaderboard-compare-snapshot/v1"
├── generated_at        : ISO 8601
├── group_count         : int
├── preferred_pair_count : int
├── groups[]            ← 每个比较维度一个 group
│   ├── scope_key       : "model|hardware|precision|workload|config_type|chip_count|node_count"
│   ├── scope           : 各维度的可读分解
│   ├── engines[]       ← 每个引擎的摘要（去重后，每引擎保留最新一条）
│   └── preferred_pair  ← 自动选出的头对头比较
│       ├── left / right : 引擎摘要 + 关键指标
│       ├── deltas       : 相对差值（%）
│       └── winners      : throughput / ttft / tbt 各维度胜者
├── preferred_pairs[]   ← 与 groups 相同，方便前端快速渲染
└── hard_constraints    ← 硬约束快照（见 §4.4）
```

### 3.3 leaderboard_manifest.json（导出索引）

```json
{
  "schema_version": "leaderboard-export-manifest/v2",
  "generated_at": "...",
  "entries": [
    {
      "idempotency_key": "<sha256>",
      "leaderboard_artifact": "foo_leaderboard.json"
    }
  ]
}
```

---

## 4. 业务处理逻辑

### 4.1 Benchmark 侧导出（leaderboard_export.py）

`export_leaderboard_artifacts()` 接受以下两种输入形式，生成标准 artifact：

**输入形式 A（直接格式）：**
```
metrics_file.json
  └── { metrics: {...}, constraints_metrics: {...} }
```

**输入形式 B（派生格式）：**
```
benchmark_result.json  +  constraints_file.json
```
- 从 `benchmark_result.json` 字段中派生关键指标：
  - `ttft_ms`：优先取 `mean_ttft_ms`，退化到 `avg_latency × 1000`
  - `throughput_tps`：依次尝试 `output_throughput` / `tokens_per_second` / `total_token_throughput` / `requests_per_second`
  - `error_rate`：`failed / (completed + failed)`

**幂等性键计算：**
```python
idempotency_key = sha256(
    "|".join([scenario_name, engine, engine_version, model_name,
              hardware_chip_model, str(chip_count), str(node_count), run_id])
)
```

**生成产物：**
- `<artifact_name>_leaderboard.json`（标准 entry 格式）
- `leaderboard_manifest.json`（指向 artifact 的索引）

---

### 4.2 聚合脚本（aggregate_results.py）

#### 步骤 1：加载并验证

```
rglob("leaderboard_manifest.json")
  → 检查 schema_version in {v1, v2}
  → 读取 entries[].leaderboard_artifact → 加载 JSON
  → Draft7Validator 验证（leaderboard_v1.schema.json）
  → 校验 manifest 与 artifact 中的 idempotency_key 一致
```

#### 步骤 2：去重

```python
# 相同 idempotency_key 保留更新的一条
# 判断依据：metadata.submitted_at > metadata.release_date（时间戳更大优先）
# 时间戳相同时：throughput_tps 更高优先
```

#### 步骤 3：拆分 single / multi

```python
if (entry.cluster or {}).get("node_count", 1) > 1:
    multi.append(entry)
else:
    single.append(entry)
```

#### 步骤 4：输出

- `leaderboard_single.json`：单节点条目数组（按 engine / model / workload / submitted_at 排序）
- `leaderboard_multi.json`：多节点条目数组（同上）
- `leaderboard_compare.json`：由 `build_compare_snapshot()` 生成（见 §4.3）
- `last_updated.json`：`{ "last_updated": "<UTC now>" }`

---

### 4.3 比较快照（Compare Snapshot）

`build_compare_snapshot(entries)` 的核心逻辑：

#### 1. 按"比较维度"分组

```python
scope_key = "|".join([
    model_name, chip_model, precision,
    workload_name, config_type,
    str(chip_count), str(node_count)
])
```

#### 2. 每组内按引擎去重

- 同一组内，相同 `engine` 的多条记录只保留最新的（`prefer_newer_entry`）

#### 3. 选 preferred_pair

- 要求 **≥ 2 个不同引擎**才构成有效 compare group
- 按以下优先级排序，取前两名作为 left / right：
  1. `throughput_tps` 降序（越高越好）
  2. `ttft_ms` 升序（越低越好）
  3. `tbt_ms` 升序
  4. engine 名称 / 版本字符串

#### 4. 计算 delta

```python
delta_pct = (left_value - right_value) / |right_value| × 100
```

- `throughput_pct_left_vs_right`（正值 → left 更快）
- `ttft_pct_left_vs_right`（负值 → left 延迟更低）
- `tbt_pct_left_vs_right`

#### 5. 判断 winner

```python
winner = "left" / "right" / "parity" / "unknown"
# throughput：higher_is_better=True
# ttft、tbt：higher_is_better=False
```

---

### 4.4 硬约束评估（Hard Constraints）

`evaluate_hard_constraints(entry)` 检查 4 项硬性指标，阈值固定于代码中：

| 检查项 | 字段来源 | 阈值 |
|--------|----------|------|
| **effective_utilization_ge_90** | `constraints.metrics.single_chip_effective_utilization_pct` | ≥ 90% |
| **typical_scene_ge_2x_and_ttft_tpot_reduction_gt_20** | `typical_throughput_ratio_vs_baseline`<br>`typical_ttft_reduction_pct_vs_baseline`<br>`typical_tpot_reduction_pct_vs_baseline` | ≥ 2.0x<br>> 20%<br>> 20% |
| **long_context_ge_32k_and_p95_p99_stable** | `long_context_length`<br>`long_context_throughput_stable`<br>`long_context_ttft/tpot_p95/p99_stable` | ≥ 32768<br>全为 True |
| **single_business_cost_down_ge_30_and_multi_tenant_high_utilization** | `unit_token_cost_reduction_pct`<br>`multi_tenant_high_utilization` | ≥ 30%<br>True |

`overall_pass = ALL(4 checks pass)`

`build_hard_constraint_snapshot(entries)` 将所有 entry 按"硬约束维度"分组（以 engine / model / hardware / workload / config_type / business_scenario / baseline_engine 为 scope_key），每组保留最新一条和上一条，计算各关键指标的 delta：

| delta 字段 | 含义 |
|------------|------|
| `single_chip_effective_utilization_pct` delta | 较上次的利用率变化 |
| `typical_throughput_ratio_vs_baseline` delta | 较上次的吞吐比变化 |
| `typical_ttft/tpot_reduction_pct_vs_baseline` delta | 延迟降低幅度变化 |
| `unit_token_cost_reduction_pct` delta | 单 token 成本降低幅度变化 |

---

### 4.5 HuggingFace 发布（hf_publisher.py）

`upload_leaderboard_to_hf()` 将聚合产物上传至 HF Dataset：

- 必须上传的文件：`leaderboard_single.json`, `leaderboard_multi.json`, `leaderboard_compare.json`, `last_updated.json`
- 可选文件：`hard_constraints.json`
- Token 解析顺序：`token` 参数 → `HF_TOKEN` 环境变量 → `huggingface-cli login` 缓存
- Repo 不存在时自动创建（私有）

---

### 4.6 前端渲染（index.html）

网站 `index.html` 包含 **Performance Leaderboard** 板块，通过 JavaScript 完成：

1. **数据加载**：`fetch('data/leaderboard_single.json')` 等（或从 HF Dataset 远程拉取）
2. **Quick View**：单机 / 多机 Tab 切换
3. **过滤器**：按芯片型号、模型名称、精度、workload 名称筛选
4. **Compare 卡**：渲染 `preferred_pair` 中的 left vs right，展示 delta 和 winner
5. **Hard Constraints 状态**：显示 4 项检查的通过/失败，以及 metric delta

---

## 5. CI/CD 流水线

### vllm-hust-website

| 工作流 | 触发 | 功能 |
|--------|------|------|
| `ci.yml` | push / PR → main / main-dev | pre-commit + pytest + 验证 git hook 模板 |
| `check-stale-versions.yml` | 定期 / 手动 | 检查数据中的过期版本引用 |
| `sync-version-meta.yml` | 手动 / schedule | 同步版本元数据 |
| `sync-changzheng-hf-release.yml` | 手动 | 同步"长征"发布到 HF |
| `version-source-guard.yml` | push / PR | 防止版本字段手工篡改 |

> **当前缺失**：没有自动从 HF Dataset 拉取最新 leaderboard 数据并更新 `data/` 的工作流。

---

## 6. 当前数据状态

### leaderboard_single.json（2026-04-17）

| 字段 | 值 |
|------|----|
| 条目数 | 1 |
| Engine | vllm-ascend 0.17.2rc1.dev450 |
| 硬件 | Huawei 910B2 × 1 |
| 模型 | Qwen2.5-7B-Instruct (BF16) |
| Workload | sharegpt-online |
| TTFT | 1916.74 ms |
| Throughput | 154.58 tps |
| 硬约束 metrics | **全部为 null** |

### leaderboard_multi.json

当前为空数组 `[]`。

### leaderboard_compare.json

- `group_count: 0`（因为只有 1 个引擎，无法构成对比组）
- `hard_constraints.pass_count: 0, fail_count: 1`（所有硬约束检查均因 null 值而失败）

---

## 7. 存在的问题

### P0 — 功能阻塞

| 编号 | 问题 | 影响 |
|------|------|------|
| P0-1 | **硬约束 metrics 全为 null**：当前唯一条目的 `constraints.metrics` 中所有硬约束指标均为 null，导致 4 项检查全部失败，无法通过任何 hard constraint。 | 核心功能不可用 |
| P0-2 | **只有单引擎数据**：`group_count=0`，compare snapshot 无内容，前端 Compare 卡无数据可渲染。 | 核心功能不可用 |
| P0-3 | **leaderboard_multi.json 为空**：多机部分完全没有数据。 | 多机功能不可用 |

### P1 — 数据质量

| 编号 | 问题 |
|------|------|
| P1-1 | `workload.name` 字段缺失（当前仅有 `"name": "sharegpt-online"` 但多处依赖此字段做 scope_key 分组）。 |
| P1-2 | `hardware.interconnect = "unknown"`，导致 FORMAT_CHANGES.md 中已定义的 `intra_node_interconnect` / `inter_node_network` 语义分离未落地。 |
| P1-3 | `metadata.reproducible_cmd = null`，可复现性无法保证。 |
| P1-4 | `environment.pytorch_version / cuda_version / cann_version` 全为 null，运行环境不可追溯。 |
| P1-5 | `metadata.git_commit = null`，代码版本无法溯源。 |

### P2 — 架构与流程

| 编号 | 问题 |
|------|------|
| P2-1 | **HF Dataset 依赖**：网站主路径依赖 HF Dataset，在国内网络受限环境下可能不可访问，存在可用性风险。 |
| P2-2 | **无自动化数据更新 CI**：每次 benchmark 结果更新需手动执行 `sync_results_to_website.sh` 或 `upload-hf`，没有自动触发流水线。 |
| P2-3 | **manifest schema 版本混用**：代码同时支持 `v1` 和 `v2`，版本兼容逻辑分散，易出错。 |
| P2-4 | **硬约束阈值硬编码**：`HARD_CONSTRAINT_THRESHOLDS` 写死于 `aggregate_results.py`，无法通过配置调整，扩展性差。 |
| P2-5 | **前端直接读取本地 JSON**：无 API 层，无法动态分页/筛选大量数据，随数据量增长会出现性能问题。 |
| P2-6 | **leaderboard_compare.json 无版本追踪**：派生快照不记录基于哪些 artifact 版本生成，重新生成后无法与旧版对比。 |
| P2-7 | **`preferred_pair` 选择策略缺少配置**：当前按 throughput → ttft → tbt 排序选 preferred_pair，无法根据业务场景定制（如强调延迟的在线场景应优先考虑 ttft）。 |

### P3 — 工程质量

| 编号 | 问题 |
|------|------|
| P3-1 | `generate_rich_data.py` 生成的测试数据与真实数据混存于 `data/`，容易造成混淆。 |
| P3-2 | `data/results/cpu/gpt2/` 下存在旧式目录格式的 artifact（不含 `constraints` 字段），与当前 v1 schema 不完全兼容。 |
| P3-3 | 前端 Leader Board 渲染逻辑内嵌在 82KB 的 `index.html` 中，缺乏模块化，维护困难。 |

---

## 8. 优化方向

### O1. 补全硬约束指标采集管道（优先级：P0）

在 `vllm-hust-benchmark` 的 benchmark 执行流程中，**必须采集并写入** `constraints_metrics` 的全部字段：

- `single_chip_effective_utilization_pct`：通过 NPU/GPU 利用率监控获取（如 `npu-smi` / `nvidia-smi`）
- `typical_throughput_ratio_vs_baseline`：运行基线引擎（vllm 原版），计算比值
- `typical_ttft/tpot_reduction_pct_vs_baseline`：同上，取延迟降幅
- `long_context_*`：新增长文本 workload（≥ 32K token），采集 P95/P99 稳定性

### O2. 补充多引擎对比数据（优先级：P0）

在同一硬件 / 模型 / 负载配置下，同时运行 `vllm-ascend`（基线）和 `vllm-hust`（优化版），将两条记录写入同一 `leaderboard_single.json`，才能构成有效 compare group。

### O3. 自动化 benchmark → website 数据更新流水线（优先级：P1）

```
vllm-hust-benchmark CI
  → 执行 benchmark
  → export artifacts
  → (可选) upload-hf
  → 触发 vllm-hust-website workflow_dispatch
      → aggregate_results.py
      → commit & push data/leaderboard_*.json
```

### O4. 引入 HF 降级方案（优先级：P1）

对于国内部署场景：
- 优先尝试从配置的 HF mirror（如 `hf-mirror.com`）拉取
- 降级到 website `data/` 目录下的本地快照
- 或部署国内自建 CDN 托管 leaderboard JSON 文件

### O5. 硬约束阈值外部化配置（优先级：P2）

将 `HARD_CONSTRAINT_THRESHOLDS` 从代码中提取到 `data/hard_constraint_thresholds.json`（或 schema 文件），支持按场景配置不同阈值。

### O6. 前端模块化与分页（优先级：P2）

- 将 Leader Board 渲染逻辑提取为独立 JS 模块（或迁移至 `vllm-hust-workstation` 的 Next.js 应用）
- 当数据量超过 100 条时，改为服务端分页 API，避免前端一次性加载全量数据

### O7. `preferred_pair` 选择策略可配置化（优先级：P2）

引入 `compare_strategy` 配置参数，支持：
- `throughput-first`（当前默认）
- `latency-first`（在线交互场景）
- `cost-first`（结合 `unit_token_cost_reduction_pct`）

### O8. 补全 `reproducible_cmd` 与环境信息（优先级：P1）

在 `leaderboard_export.py` 中自动采集：
- `metadata.reproducible_cmd`：记录完整的执行命令
- `environment.pytorch_version`：从 `torch.__version__` 读取
- `environment.cann_version`：从 `torch_npu` 或 `/usr/local/Ascend/` 读取
- `environment.cuda_version`：从 `torch.version.cuda` 读取
- `metadata.git_commit`：从 `git rev-parse HEAD` 读取

### O9. 清理历史遗留数据格式（优先级：P3）

- 将 `data/results/cpu/gpt2/` 下的旧 artifact 迁移到 manifest 模式
- 或将其排除在 `aggregate_results.py` 扫描范围之外
- 明确 `generate_rich_data.py` 为测试工具，禁止其输出污染 `data/`

### O10. 监控与告警（优先级：P3）

- 增加 CI 检查：`leaderboard_compare.json` 的 `group_count` > 0，否则告警
- 增加 CI 检查：hard constraints `pass_count / scope_count` 不低于预设阈值
- 增加 `last_updated.json` 过期检查（超过 N 天未更新则告警）
