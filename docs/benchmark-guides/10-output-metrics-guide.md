# 输出指标解读

本文档说明 benchmark output 的指标体系。输入参数见 [03-params-outputs-reference.md](03-params-outputs-reference.md),路径选择见 [02-benchmark-paths.md](02-benchmark-paths.md)。submission/snapshot 整体产出体系(指标存放在哪个文件、如何派生)见 [11-submission-snapshot-output.md](11-submission-snapshot-output.md)。

## metrics 5 字段

`run_leaderboard.json` 顶层 `metrics` 对象共 5 个字段。

| 字段名 | 类型 | 单位 | 含义 | 典型范围 | 出现在哪些 workload |
|--------|------|------|------|----------|---------------------|
| `ttft_ms` | number \| null | ms | 首 Token 延迟(serve 类取 `mean_ttft_ms`;latency 类复用为 batch 端到端延迟取 `avg_latency*1000`);throughput 类恒为 null | online: 132-336 ms;latency: ~7000-9700 ms;throughput: null | 全部(throughput 下为 null) |
| `tbt_ms` | number \| null | ms | Token 间延迟,取自 raw 的 `mean_tpot_ms`(优先)或 `mean_tbt_ms`/`tpot_ms`/`tbt_ms` | online: 34-47 ms;latency 与 throughput: null | 仅 online 类有数值 |
| `throughput_tps` | number \| null | tokens/s | 输出吞吐,取自 raw 的 `output_throughput`(优先)或 `tokens_per_second`/`total_token_throughput`/`request_throughput` | online: 200-245;throughput: 1383-4648;latency: null | online 与 throughput;latency 下为 null |
| `peak_mem_mb` | integer \| null | MB | 单次运行峰值显存占用 | 当前实测均为 0(采集未落地) | 全部 |
| `error_rate` | number \| null | 比率 0-1 | 请求失败数 / 总请求数 | 0.0(成功);latency 历史样本可能为 null | 全部 |

代码语义:

- `benchmark_type == "throughput"`:`ttft_ms` 强制 null(离线无首 token 语义)
- `benchmark_type == "latency"`:`throughput_tps` null,`error_rate` 0.0
- latency 类的 `ttft_ms` 是 batch 端到端延迟,**不可与 online 的 ttft_ms 横比**

## constraints.metrics 16 字段

| 字段名 | 类型 | 单位 | 含义 | 典型约束值 |
|--------|------|------|------|-----------|
| `single_chip_effective_utilization_pct` | number \| null | % | 单卡有效利用率 | 目标 > 90;实测样本 null |
| `typical_throughput_ratio_vs_baseline` | number \| null | 倍率 | 相对基线吞吐倍率 | 2.2(sample);目标 ≥ 2.0 |
| `typical_ttft_reduction_pct_vs_baseline` | number \| null | % | 相对基线 TTFT 降幅 | 23.0(sample);目标 ≥ 20 |
| `typical_tpot_reduction_pct_vs_baseline` | number \| null | % | 相对基线 TPOT 降幅 | 25.0(sample);目标 ≥ 25 |
| `long_context_length` | integer \| null | tokens | 长上下文长度(取自 resolved max_model_len) | 32768(online);null(latency/throughput) |
| `long_context_throughput_stable` | boolean \| null | - | 长上下文吞吐是否稳定(completed>0 且 failed==0 且 throughput>0) | true(online);false(latency/throughput) |
| `long_context_ttft_p95_ms` | number \| null | ms | 长上下文 TTFT P95 | 80.0(sample);实测多 null |
| `long_context_ttft_p99_ms` | number \| null | ms | 长上下文 TTFT P99 | 95-1461(实测) |
| `long_context_tpot_p95_ms` | number \| null | ms | 长上下文 TPOT P95 | 9.0(sample);实测多 null |
| `long_context_tpot_p99_ms` | number \| null | ms | 长上下文 TPOT P99 | 10-54(实测) |
| `long_context_ttft_p95_stable` | boolean \| null | - | TTFT P95 是否稳定 | true(sample) |
| `long_context_ttft_p99_stable` | boolean \| null | - | TTFT P99 是否稳定 | true(online) |
| `long_context_tpot_p95_stable` | boolean \| null | - | TPOT P95 是否稳定 | true(sample) |
| `long_context_tpot_p99_stable` | boolean \| null | - | TPOT P99 是否稳定 | true(online) |
| `unit_token_cost_reduction_pct` | number \| null | % | 单 token 推理成本降幅 | 35.0(sample) |
| `multi_tenant_high_utilization` | boolean \| null | - | 多租户高并发利用率是否达标 | true(sample) |

派生逻辑:

- `long_context_length` 来自 `same_spec.resolved_server_parameters.max_model_len`
- `long_context_throughput_stable = completed>0 and failed==0 and throughput>0`
- 四个 `*_stable` 字段在对应 p95/p99 raw 值存在时赋同 `is_stable`,否则 null
- latency/throughput 类因 `max_model_len` 不在 resolved_server_parameters,`long_context_length` 为 null,`long_context_throughput_stable` 为 false

## 不同 workload 类型指标差异

| workload 类型 | 核心指标(前 3 个) | 次要指标 | 关注点 | 典型数值范围 |
|---------------|-------------------|----------|--------|-------------|
| latency 类(`random-latency`) | `ttft_ms`(实为 batch 端到端延迟)、`peak_mem_mb`、`error_rate` | 无 tbt/throughput | 固定 batch=8 下端到端延迟稳定性,10 预热+30 迭代 | ttft_ms ~7000-9700 ms;throughput_tps=null;tbt_ms=null |
| throughput 类(`sharegpt-throughput`、`sonnet-throughput`) | `throughput_tps`、`peak_mem_mb`、`error_rate` | 无 ttft/tbt | 离线批处理最大吞吐,不限 QPS,引擎自调度 | sharegpt ~1383 tps;sonnet ~4283-4648 tps;ttft_ms=null;tbt_ms=null |
| online 类(`random-online`、`sharegpt-online`、`prefix-repetition-online`、`instructcoder-online`、`visionarena-online`、`agent-research-online`) | `ttft_ms`、`tbt_ms`、`throughput_tps` | `peak_mem_mb`、`error_rate`;以及 `constraints.metrics.long_context_*_p99_ms` | Poisson 到达(QPS=1)下 TTFT/ITL 分布、吞吐与稳定性 | ttft 132-336 ms;tbt 34-47 ms;throughput 200-245 tps |

## 官方基线参照

910B2 单卡 + vLLM v0.18.0 官方基线(来自 `docs/国产芯片大模型推理关键指标与基线评测方案.md`)。

| workload | TTFT (ms) | TBT (ms) | Throughput (tps) |
|----------|-----------|----------|-----------------|
| random-online | 271.10 | 72.78 | 227.14 |
| sharegpt-online | 152.62 | 71.78 | 185.03 |
| prefix-repetition-online | 227.98 | 74.26 | 234.25 |
| sharegpt-throughput | null | null | 1383.05 |
| sonnet-throughput | null | null | 4283.21 |
| random-latency | 9671.39 | null | null |

## 核心指标好坏判断与优化方向

### `ttft_ms`(首 Token 延迟)

- **好坏判断**:online 场景 < 300ms 正常(基线 271ms),> 500ms 算[回归](08-regression-bisect-sop.md),> 1000ms 严重回归(prefix-repetition 实测 P99 可达 1461ms,均值 336ms 偏高需关注);latency 场景 < 9700ms 正常,但该值是 batch 端到端延迟,**不可与 online 的 ttft_ms 横比**
- **两次对比看哪个字段**:`metrics.ttft_ms`(均值);尾延迟看 `constraints.metrics.long_context_ttft_p99_ms`
- **优化方向**:TTFT 高 → 查 [prefix cache](09-multi-chip-and-research.md) 命中率、[KV cache](09-multi-chip-and-research.md) prefill chunk size、是否 `enforce_eager` 关闭图模式、attention/prefill 算子性能

### `tbt_ms`(Token 间延迟,即 TPOT 均值)

- **好坏判断**:基线 ~73ms;< 55ms 达标(目标降 25%+);> 80ms 算[回归](08-regression-bisect-sop.md)。实测 codex-main 已到 34-47ms,优于基线
- **两次对比看哪个字段**:`metrics.tbt_ms`(均值);尾延迟看 `constraints.metrics.long_context_tpot_p99_ms`
- **优化方向**:tbt 高 → 查 decode 阶段算子、[KV cache](09-multi-chip-and-research.md) 访问模式、是否开启 chunked prefill 干扰、scheduler batch 构建策略

### `throughput_tps`(输出吞吐)

- **好坏判断**:throughput 类核心,sonnet 目标 ≥ 2× 基线(8566+ tps);online 类 200-245 tps 正常。值下降 > 5% 算[回归](08-regression-bisect-sop.md)
- **两次对比看哪个字段**:`metrics.throughput_tps`;基线对比看 `constraints.metrics.typical_throughput_ratio_vs_baseline`(目标 ≥ 2.0)
- **优化方向**:throughput 低 → 查 batch size 上限、`gpu_memory_utilization`、continuous batching 调度、decode 与 prefill 混合比、算子融合

### `peak_mem_mb`(峰值显存)

- **好坏判断**:当前实测均为 0(采集未落地),无法据此判断;`constraints.metrics.single_chip_effective_utilization_pct` 是替代指标,目标 > 90%
- **优化方向**:显存高 → 查 [KV cache](09-multi-chip-and-research.md) block 大小、是否内存碎片、模型加载 dtype

### `error_rate`(错误率)

- **好坏判断**:必须为 0.0;> 0 直接判失败,通常伴随 `long_context_throughput_stable=false`
- **优化方向**:非 0 → 查 OOM、请求超时、server crash、`max_model_len` 不足导致请求被拒

## raw / run_leaderboard / manifest 三者关系

| 文件 | 产出方 | 内容 | 对外稳定性 |
|------|--------|------|-----------|
| `raw_benchmark_result.json` | vllm-hust 的 `vllm bench serve/throughput/latency` 直接产出 | 原始结果,字段名跟随 vllm 上游(如 `mean_ttft_ms`、`mean_tpot_ms`、`output_throughput`、`completed`、`failed`、`p99_ttft_ms`、`p99_tpot_ms`、`avg_latency`、`duration`、`total_input_tokens`) | 不稳定,字段随 vllm 版本变化 |
| `run_leaderboard.json` | `leaderboard_export.py` 从 raw + constraints + same_spec 派生 | 标准化单条记录,website 聚合与 HF 同步的标准 schema-compatible。含 `entry_id`、`engine`/`engine_version`、`config_type`、`hardware`、`model`、`workload`、`metrics`(5 字段)、`constraints`(含 `metrics` 16 字段)、`cluster`、`versions`、`environment`、`metadata`(含 `idempotency_key`、`runtime_provenance`、`git_commit`)、`same_spec` | 稳定(仓库自有契约) |
| `leaderboard_manifest.json` | `leaderboard_export.py` 产出 | 极简索引,仅声明 `schema_version`(`leaderboard-export-manifest/v2`)、`generated_at`、`entries` 数组(每项含 `idempotency_key` 与 `leaderboard_artifact` 文件名) | 稳定 |

派生链:`raw_benchmark_result.json` →(exporter 派生)→ `run_leaderboard.json` + `leaderboard_manifest.json`

关键规则:

- 对外稳定边界是 `run_leaderboard.json` 与 `leaderboard_manifest.json`,不是 raw
- `benchmark_type` 决定 `run_leaderboard.json` 的哪些 metrics 字段被置 null
- `idempotency_key` 由 `scenario+engine+engine_version+model_identity+chip_model+chip_count+node_count+run_id` 的 SHA-256 生成,用于聚合器去重
- 数据错误须回 exporter 源头修正,不应在 website 自行修补单条 entry

## 性能分析分层指引:看哪个文件、看哪些指标

性能分析分三层递进:**先选文件,再选指标,最后按角色裁剪**。不要一上来就翻 raw。

### 第 1 层:看哪个 output 文件

按分析目标选文件,不要全看。

| 分析目标 | 看哪个文件 | 为什么 |
|---------|-----------|--------|
| 快速判断本次跑得好不好 | submission 的 `run_leaderboard.json` | 5+16 字段已标准化,直接对比基线 |
| 横向对比 vllm vs vllm-hust | snapshot 的 `leaderboard_compare.json` | 已按 same_spec scope 分组,同条件对比 |
| 看趋势/找回归 commit | 多个 submission 的 `run_leaderboard.json` 串联 | 标准化字段可横比,raw 不行 |
| 深度排查某个指标的尾延迟 | submission 的 `raw_benchmark_result.json` | raw 有 p95/p99/avg_latency 等 run_leaderboard 没有的字段 |
| 排查 entry 没进网站 | snapshot 的 `rejected_superseded_report.json` + `admission_report.json` | 看被拒/被隔离原因 |
| 排查环境/复现问题 | submission 的 `env-manifest.json` + `pip-packages.json` + `server.stdout.log` | 看依赖版本、git commit、服务端日志 |
| 网站访客视角 | snapshot 的 `leaderboard_single.json` / `leaderboard_multi.json` | 这就是网站数据源 |

**一句话优先级**:`run_leaderboard.json` 是性能分析的主战场;raw 是深挖尾延迟时才看;snapshot 报告是排查"数据没进网站"时才看。

### 第 2 层:看哪些指标(按目标分层)

`run_leaderboard.json` 里 5 个 metrics + 16 个 constraints.metrics,不是每个都要看。按目标分层:

**健康度(每次必看,不过关直接停)**

| 指标 | 判定 |
|------|------|
| submission 的 `STATUS` | 必须 `OK` |
| `metrics.error_rate` | 必须 `0.0`;> 0 直接判失败 |
| `constraints.metrics.long_context_throughput_stable`(online 类) | 必须 `true` |

**核心性能(online 类:random-online / sharegpt-online / prefix-repetition-online 等)**

| 指标 | 看均值还是尾延迟 | 好坏判定 |
|------|-----------------|---------|
| `metrics.ttft_ms` | 均值 | < 300ms 正常,> 500ms 回归 |
| `metrics.tbt_ms` | 均值 | < 55ms 达标,> 80ms 回归 |
| `metrics.throughput_tps` | 均值 | 200-245 tps 正常,降 > 5% 回归 |
| `constraints.metrics.long_context_ttft_p99_ms` | 尾延迟 | 关注是否突增(实测 95-1461ms) |
| `constraints.metrics.long_context_tpot_p99_ms` | 尾延迟 | 关注是否突增(实测 10-54ms) |

**核心性能(throughput 类:sharegpt-throughput / sonnet-throughput)**

| 指标 | 好坏判定 |
|------|---------|
| `metrics.throughput_tps` | sharegpt ~1383;sonnet ~4283-4648;目标 ≥ 2× 基线 |
| `ttft_ms` / `tbt_ms` | 恒为 null,不用看 |

**核心性能(latency 类:random-latency)**

| 指标 | 好坏判定 |
|------|---------|
| `metrics.ttft_ms` | ~7000-9700ms(是 batch 端到端延迟,**不可与 online 横比**) |
| `throughput_tps` / `tbt_ms` | 恒为 null,不用看 |

**基线对比(vllm-hust vs vllm 优化效果)**

| 指标 | 目标 |
|------|------|
| `constraints.metrics.typical_throughput_ratio_vs_baseline` | ≥ 2.0 |
| `constraints.metrics.typical_ttft_reduction_pct_vs_baseline` | ≥ 20 |
| `constraints.metrics.typical_tpot_reduction_pct_vs_baseline` | ≥ 25 |
| `constraints.metrics.unit_token_cost_reduction_pct` | 35(sample) |

**资源利用(当前参考价值有限)**

| 指标 | 状态 |
|------|------|
| `metrics.peak_mem_mb` | 实测均为 0(采集未落地),暂不可用 |
| `constraints.metrics.single_chip_effective_utilization_pct` | 目标 > 90;实测多 null |

### 第 3 层:按角色裁剪

| 角色 | 主要看 | 次要看 |
|------|--------|--------|
| 引擎开发者(自己跑验证) | submission 的 `run_leaderboard.json` 5 metrics | raw 看 p99 尾延迟;`server.stdout.log` 排障 |
| Paul(Backfill/Leaderboard 完整性) | 多个 submission 的 `run_leaderboard.json` 趋势 | snapshot 的 `rejected_superseded_report` + `admission_report` 排查 entry 去向 |
| 回归调查(性能回归二分) | 多个 commit 的 `run_leaderboard.json` 串联看 `ttft_ms`/`tbt_ms`/`throughput_tps` 趋势 | raw 的 p99 看尾延迟突跳;详见 [08-regression-bisect-sop.md](08-regression-bisect-sop.md) |
| 网站访客 | snapshot 的 `leaderboard_compare.json`(同 scope vllm vs vllm-hust) | `leaderboard_single.json` 看绝对值 |
| CI/perfgate reviewer | submission 的 `STATUS` + `error_rate` + 5 metrics 是否过 gate | `env-manifest.json` 校验环境一致性 |

### 常见误用

- **拿 online 的 `ttft_ms` 跟 latency 的 `ttft_ms` 横比** → 字段同名但语义不同(latency 是 batch 端到端延迟)
- **拿 raw 的字段做跨 commit 趋势分析** → raw 字段随 vllm 版本变,不稳定的字段不能做趋势;用 `run_leaderboard.json` 的 5 metrics
- **看 `peak_mem_mb` 判断显存** → 当前都是 0,采集没落地,看不了
- **从文件名推断 `910B2`/`FP16`** → 禁止,权威字段在 `run_leaderboard.json` 内
- **拿两个 vllm-hust 版本互比当基线** → `agent.md` 明示:必须对比同 spec 的 `vllm` baseline,不能 vllm-hust 自比
