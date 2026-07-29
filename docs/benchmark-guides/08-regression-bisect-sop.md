# 性能回归二分定位 SOP

## 适用场景

当发现某个 commit 导致性能回归(如 TTFT 翻倍、throughput 下降 40%)时,用本 SOP 做二分定位。本 SOP 覆盖 4 个核心 issue:#58(Ngram 3x TPOT)、#146(7 月区间)、#151(6 个跳变)、#163(Prefix 78%)。多卡回归见 [09-multi-chip-and-research.md](09-multi-chip-and-research.md)。

## 通用 bisect 模板

5 步流程:

```
1. 确定回归 commit range(good_commit..bad_commit)
2. 用 git bisect 或手工二分找中点 mid_commit
3. 跑路径 C(单卡 backfill)在中点 commit 上的 benchmark:
   python3 scripts/backfill_single_gpu.py run --commit <mid_commit> --workload <name>
4. 比对结果(metrics.ttft_ms / throughput_tps,见 [10-output-metrics-guide.md](10-output-metrics-guide.md))
5. 若 mid 仍回归 → range = mid..bad;若 mid 正常 → range = good..mid;重复直到定位
```

可复制命令:

```bash
cd $WORKSPACE_ROOT/vllm-hust-benchmark

# 启动 git bisect(在 vllm-hust 仓内)
cd $WORKSPACE_ROOT/vllm-hust
git bisect start
git bisect bad <bad_commit>
git bisect good <good_commit>

# git 会给出中点,记下 mid_commit,回 benchmark 仓跑
cd $WORKSPACE_ROOT/vllm-hust-benchmark
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload <workload_name>

# 跑完后回 vllm-hust 仓标记
cd $WORKSPACE_ROOT/vllm-hust
git bisect good   # 或 git bisect bad
# 重复直到 git 报告 "first bad commit"
git bisect reset
```

## 路径 G(重复跑)与 bisect 串联

为什么需要:单次 benchmark 有 noise(±5-10%),回归幅度 < 20% 时单跑无法区分 noise vs 真回归。

串联方法:每个 bisect 中点用路径 G 跑 3 次取中位数。

```bash
# 在中点 commit 跑 3 次
cd $WORKSPACE_ROOT/vllm-hust-benchmark
bash scripts/run-campaign-repetitions.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-<workload>-qwen25-14b-910b2.json \
  --campaign-prefix bisect-<mid_commit> \
  --repetitions 3

# 3 份 artifact 在 submissions/bisect-<mid_commit>-<workload>-1chip-<ts>/
# 取 3 次的 metrics.ttft_ms 中位数作为该 commit 的代表值
```

判断规则:

| 3 次中位数 vs good_commit 中位数变化 | 结论 |
|------------------------------------|------|
| > 10% | 真回归 |
| < 5% | noise,可接受 |
| 5%-10% | 增加 repetitions 到 5 次再判断 |

## #58 专用配置(Ngram 3x TPOT 回归)

### issue 背景

| 项 | 值 |
|----|----|
| issue | core #58 |
| 现象 | TPOT 从 32ms 涨到 106ms(3.3x 回归) |
| 怀疑 | Ngram 相关改动导致 decode 阶段性能下降 |

### 专用配置:eager vs graph 对比

Ngram 可能影响图模式优化,需对比 eager 与 graph 两种模式:

```bash
# 跑 graph 模式(默认,enforce_eager 为空)
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload random-online

# 跑 eager 模式(需在 spec 文件的 server_parameters 里设 enforce_eager="1")
# 先复制一份 spec 改 enforce_eager
cp docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json \
   docs/official-baselines/bisect-58-eager-random-online.json
# 编辑 bisect-58-eager-random-online.json,在 server_parameters 加 "enforce_eager": "1"
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload random-online
```

判断:

| graph 模式 | eager 模式 | 结论 |
|-----------|-----------|------|
| 回归 | 正常 | 图模式优化被破坏 |
| 回归 | 回归 | decode 算子本身回归 |
| 正常 | 正常(但 Ngram 场景回归) | Ngram 调度逻辑问题 |

### 诊断辅助:路径 F msprof

```bash
bash scripts/run-current-ascend-same-spec-msprof.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json
# 看 msprof trace 里 decode 阶段的算子耗时分布
```

## #146 专用配置(7 月区间回归)

### issue 背景

| 项 | 值 |
|----|----|
| issue | core #146 |
| commit range | `2206f1f7b7`(good)→ `7a63f81e86` 或 `83cf83ff20`(bad) |
| 现象 | sonnet-throughput 与 random-online 在 7 月某区间回归 |

### 专用配置:区间二分

```bash
cd $WORKSPACE_ROOT/vllm-hust
git bisect start
git bisect bad 83cf83ff20
git bisect good 2206f1f7b7

# 每个中点跑 2 个 workload(sonnet-throughput + random-online)
cd $WORKSPACE_ROOT/vllm-hust-benchmark
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload sonnet-throughput
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload random-online
```

两个 workload 任一回归即标记该 commit 为 bad。

## #151 专用配置(6 个性能跳变)

### issue 背景

| 项 | 值 |
|----|----|
| issue | core #151 |
| 现象 | first-parent 链上有 6 个独立的性能跳变点,需逐一定位 |

### 专用配置:jump-by-jump

不是标准二分,而是逐个 first-parent commit 跑:

```bash
# 列出 first-parent 链
cd $WORKSPACE_ROOT/vllm-hust
git log --first-parent --oneline <good>..<bad>

# 对每个 first-parent commit 跑 benchmark
for commit in <commit1> <commit2> <commit3> <commit4> <commit5> <commit6>; do
  cd $WORKSPACE_ROOT/vllm-hust-benchmark
  python3 scripts/backfill_single_gpu.py run --commit $commit --workload random-online
done

# 比对 6 次结果,找出哪个 commit 导致跳变
```

建议:每个 commit 跑 3 次取中位数(用路径 G),避免 noise 干扰跳变判断。

## #163 专用配置(Prefix 78% 吞吐回归)

### issue 背景

| 项 | 值 |
|----|----|
| issue | core #163(P0) |
| 现象 | prefix-repetition-online 吞吐下降 78% |
| 怀疑 | prefix cache 行为变化 |

### 专用配置:prefix cache hit rate 采集

标准 benchmark 不直接报 prefix cache hit rate,需额外采集:

```bash
# 跑 prefix-repetition-online workload
python3 scripts/backfill_single_gpu.py run \
  --commit <mid_commit> \
  --workload prefix-repetition-online

# 同时跑路径 F msprof 采集 prefix cache 相关 trace
bash scripts/run-current-ascend-same-spec-msprof.sh \
  docs/official-baselines/official-ascend-jan-2026-v0180-prefix-repetition-online-qwen25-14b-910b2.json
```

关键看:

| 指标 | 期望/判断 |
|------|----------|
| `prefix-repetition-online` 的 `metrics.ttft_ms` | prefix cache 命中时 TTFT 应明显低于 random-online;若两者接近 → prefix cache 未命中 |
| `metrics.throughput_tps` | 下降 78% 意味着 < 50 tps(基线 234 tps) |
| msprof trace | 查 attention 算子里 prefix cache 相关的 kernel 耗时 |

对比策略:

| random-online | prefix-repetition-online | 结论 |
|--------------|--------------------------|------|
| 正常 | 回归 | prefix cache 专属问题 |
| 回归 | 回归 | 通用 decode/prefill 问题,不是 prefix cache |

在 good_commit 与 bad_commit 各跑一次 prefix-repetition-online + random-online。

## 可执行性评估表

| issue# | 文档定位 | 可执行性 | 备注 |
|--------|---------|---------|------|
| #58 | 本文档 §4 + [02-benchmark-paths.md](02-benchmark-paths.md) 路径 A/F + [10-output-metrics-guide.md](10-output-metrics-guide.md) metrics | 中 | eager vs graph 对比需手工改 spec |
| #146 | 本文档 §5 + [04-backfill-paths.md](04-backfill-paths.md) 路径 C | 中 | commit range 已知,二分可直接执行 |
| #151 | 本文档 §6 + [04-backfill-paths.md](04-backfill-paths.md) 路径 C + [02-benchmark-paths.md](02-benchmark-paths.md) 路径 G | 中 | jump-by-jump 耗时,建议并行跑 |
| #163 | 本文档 §7 + [02-benchmark-paths.md](02-benchmark-paths.md) 路径 F + [10-output-metrics-guide.md](10-output-metrics-guide.md) metrics | 低 | prefix cache hit rate 无直接指标,需 msprof 辅助 |
