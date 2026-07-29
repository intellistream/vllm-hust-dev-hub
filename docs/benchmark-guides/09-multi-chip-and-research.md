## 适用场景

本文档覆盖现有 7 篇指南未涉及的两类场景:

1. 多卡(≥2 卡)benchmark 路径(ascend #145 两卡回归)
2. KV cache 研究项目方法论(core #183)

单卡回归见 [08-regression-bisect-sop.md](08-regression-bisect-sop.md)。

## 多卡 same-spec runner 命令

### 环境变量

多卡与单卡的区别是 `ASCEND_VISIBLE_DEVICES` 指定多个设备,且 spec 文件的 `server_parameters.tensor_parallel_size` 要与卡数一致。

```bash
# 2 卡跑路径 A
export ASCEND_VISIBLE_DEVICES=0,1
export CURRENT_SERVER_PORT=8001

cd $WORKSPACE_ROOT/vllm-hust-benchmark
bash scripts/run-current-ascend-same-spec.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-sonnet-throughput-qwen25-14b-2chip-910b2.json
```

### 2 卡 spec 模板要点

2 卡 spec 与单卡 spec 的区别(以 sonnet-throughput 为例):

| 项 | 单卡 | 2 卡 |
|------|------|------|
| 文件名 | `*-910b2.json` | `*-2chip-910b2.json` |
| `server_parameters.tensor_parallel_size` | `1` | `2` |
| `cluster.chip_count` | `1` | `2` |
| `max_model_len` / `gpu_memory_utilization` | 一致 | 一致 |

现有 2 卡 spec 清单(在 `docs/official-baselines/`):

- `official-ascend-jan-2026-v0180-agent-research-online-qwen25-14b-2chip-910b2.json`
- `official-ascend-jan-2026-v0180-prefix-repetition-online-qwen25-14b-2chip-910b2.json`
- `official-ascend-jan-2026-v0180-random-online-qwen25-14b-2chip-910b2.json`
- `official-ascend-jan-2026-v0180-sharegpt-online-qwen25-14b-2chip-910b2.json`
- `official-ascend-jan-2026-v0180-sonnet-throughput-qwen25-14b-2chip-910b2.json`

另有 4 卡与 8 卡版本(sonnet-throughput 有 4chip/8chip)。

### 路径 D 多卡

路径 D `backfill_historical_pr_benchmarks.py` 默认排除多卡 spec,需 `--include-multi-chip` 显式开启:

```bash
PYTHONPATH=src python scripts/backfill_historical_pr_benchmarks.py \
  --plan-file <plan.json> \
  --managed-dev-hub \
  --include-multi-chip \
  --execute
```

## 多卡 msprof 流程

路径 F `run-current-ascend-same-spec-msprof.sh` 在多卡下的关键差异是 `--hccl=on`(默认已开),用于采集卡间通信(HCCL)trace。

```bash
export ASCEND_VISIBLE_DEVICES=0,1
bash scripts/run-current-ascend-same-spec-msprof.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-sonnet-throughput-qwen25-14b-2chip-910b2.json
```

msprof 默认 flags:`--ascendcl=on --runtime-api=on --task-time=l1 --hccl=on --type=text`

trace 解读重点:

- `--hccl=on` 产出的 HCCL 通信事件:查 AllReduce/AllGather 耗时占比
- 若 HCCL 耗时 > 总时长 30% → 通信瓶颈
- 若 HCCL 耗时 < 10% 但 throughput 仍低 → 计算/调度瓶颈(非通信)

## 多卡 bisect SOP(ascend #145)

### issue 背景

| 项 | 内容 |
|------|------|
| issue | ascend #145(P0) |
| 现象 | 两卡 throughput 下降 40-47% |
| 怀疑 | HCCL 通信或两卡调度逻辑回归 |

### bisect 流程

与单卡 bisect(见 [08-regression-bisect-sop.md](08-regression-bisect-sop.md))相同,但每中点需跑两次:

1. 单卡 baseline(排除单卡本身回归)
2. 两卡(确认多卡专属回归)

```bash
# 单卡
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload sonnet-throughput

# 两卡(需用路径 A,backfill_single_gpu.py 是单卡专用)
ASCEND_VISIBLE_DEVICES=0,1 bash scripts/run-current-ascend-same-spec.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-sonnet-throughput-qwen25-14b-2chip-910b2.json
```

判断:

- 单卡正常 + 两卡回归 → 多卡专属问题(HCCL 或 TP 调度)
- 单卡也回归 → 通用问题,先修单卡

### HCCL 通信抖动排除

两卡 benchmark 的 noise 比单卡大(HCCL 通信有抖动),建议:

- 每中点跑 5 次(不是 3 次)取中位数
- 看 P95/P99 而非均值(用 `constraints.metrics.long_context_*_p99_ms`,见 [10-output-metrics-guide.md](10-output-metrics-guide.md))
- 若 5 次的 CV(变异系数)> 15% → 通信抖动严重,bisect 结论不可信,需先稳定环境

## KV cache 研究方法论(#183)

### issue 背景

| 项 | 内容 |
|------|------|
| issue | core #183 |
| 目标 | M0-M3 四阶段研究 KV cache 机制与优化 |

### M0:测量契约模板

需采集的指标(标准 benchmark 不直接报,需额外采集或从 raw 推导):

| 指标 | 来源 | 说明 |
|------|------|------|
| KV cache 命中率 | vllm 日志或 metrics endpoint | prefix cache 命中次数 / 总请求 |
| KV 复用率 | vllm 日志 | 复用 block 数 / 总 block 数 |
| cache eviction count | vllm 日志 | 被驱逐的 block 数 |
| TTFT 分位数 | `raw_benchmark_result.json` 的 `p95_ttft_ms`/`p99_ttft_ms` | 尾延迟 |
| 显存占用 | `metrics.peak_mem_mb`(当前为 0,需修采集) | KV cache 占用显存 |

测量契约:每个实验跑 3 次,记录均值 + P95 + CV,CV > 10% 需重跑。

### M1:机制剖析入口

用路径 F msprof 采集 KV cache 相关算子:

```bash
bash scripts/run-current-ascend-same-spec-msprof.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-prefix-repetition-online-qwen25-14b-910b2.json
```

MSPROF_FLAGS 推荐(在 `scripts/run-current-ascend-same-spec-msprof.env` 改):

- 默认:`--ascendcl=on --runtime-api=on --task-time=l1 --hccl=on --type=text`
- KV cache 专项:加 `--memory=on`(采集显存分配事件)

trace 解读重点:

- attention 算子里 KV cache 读取/写入耗时
- prefix cache 相关的 memcpy 耗时
- KV cache block 分配/释放事件

### M2:消融实验 spec 模板

对照组设计(每组跑 3 次取中位数):

| 实验组 | spec 修改 | 验证什么 |
|--------|----------|---------|
| baseline | 原始 spec | 基准 |
| KV quant int8 | `server_parameters.kv_cache_dtype`: `"int8"` | KV 量化对精度/性能影响 |
| KV offload | `server_parameters.kv_cache_memory_provision`: `<value>` | KV 卸载到 CPU/DRAM |
| prefix caching off | `server_parameters.enable_prefix_caching`: `false` | prefix cache 关闭后 TTFT 变化 |
| prefix caching on | `server_parameters.enable_prefix_caching`: `true`(默认) | baseline |

可复制 spec 修改示例:

```bash
# 复制 baseline spec
cp docs/official-baselines/official-ascend-jan-2026-v0180-prefix-repetition-online-qwen25-14b-910b2.json \
   docs/spec-matrix/kv-research-int8.json
# 编辑 kv-research-int8.json,在 server_parameters 加 "kv_cache_dtype": "int8"
```

### M3:端到端泛化多卡路径

M2 验证有效的优化,在多卡场景泛化测试:

- 用 §2 的多卡 same-spec runner 跑 2 卡/4 卡
- 用 §4 的多卡 bisect 排除 HCCL 干扰
- 对比单卡 vs 多卡的加速比(理想:2 卡 throughput ≈ 1.8x 单卡)

## 可执行性评估

| 场景 | issue# | 文档定位 | 可执行性 | 备注 |
|------|--------|---------|---------|------|
| 多卡 benchmark | (通用) | 本文档 §2 + [02-benchmark-paths.md](02-benchmark-paths.md) 路径 A + [07-params-cheatsheet.md](07-params-cheatsheet.md) | 高 | 现有 2/4/8 卡 spec 齐全 |
| 多卡 msprof | (通用) | 本文档 §3 + [02-benchmark-paths.md](02-benchmark-paths.md) 路径 F | 高 | 默认 --hccl=on |
| 多卡回归 bisect | ascend #145 | 本文档 §4 + [08-regression-bisect-sop.md](08-regression-bisect-sop.md) | 中 | 需 5 次取中位数排除 HCCL 抖动 |
| KV cache 研究 M0 | core #183 | 本文档 §5 M0 | 中 | 命中率需额外采集,标准 benchmark 不直接报 |
| KV cache 研究 M1 | core #183 | 本文档 §5 M1 + [02-benchmark-paths.md](02-benchmark-paths.md) 路径 F | 中 | msprof trace 解读需经验 |
| KV cache 研究 M2 | core #183 | 本文档 §5 M2 | 高 | 消融 spec 模板可直接用 |
| KV cache 研究 M3 | core #183 | 本文档 §5 M3 + §2 | 中 | 多卡泛化需排除 HCCL |
