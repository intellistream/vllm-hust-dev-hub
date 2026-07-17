# manage-container.sh 性能测试集成方案

> **版本**: 1.0  
> **日期**: 2026-07-17  
> **目标**: 以 `manage-container.sh` 为统一入口，实现五层测试体系

---

## 1. 设计目标

### 1.1 核心原则

- **高可用**: 不破坏现有功能，异常情况有兜底，进程管理有超时保护
- **高维护**: 遵循现有代码风格，职责单一，配置集中，环境变量驱动
- **易用性**: 一键触发，合理默认值，`--help` 完备，结果自动归档

### 1.2 五层测试体系映射

| 层 | 名称 | manage-container.sh action | 耗时 | 关键指标 |
|----|------|--------------------------|------|---------|
| L1 | 快速健康检查 | `profile --kind engine` | ~30s | 基础吞吐量、KV Cache |
| L2 | 服务级基准测试 | `benchmark` | ~5min | TTFT/TPOT/ITL/Throughput |
| L3 | 框架级 Profiling | `profile --kind torch` | ~3min | 算子级 trace |
| L4 | 硬件级 Profiling | `profile --kind msprof` | ~2min | kernel trace + TraceLoom |
| L5 | 长稳与压力测试 | `benchmark` 多次执行 | ≥1h | 性能退化检测 |

### 1.3 5 个核心组件覆盖

| 核心组件 | 集成方式 | 验证路径 |
|---------|---------|---------|
| Prometheus 指标 | `profile --kind engine` 周期性抓取 `/metrics` | 输出 `*.prom` 文件 |
| PyTorch Profiler | `profile --kind torch` 自动注入 `--profiler-config` | 输出 `*.pt.trace.json.gz` |
| Benchmark CLI | `benchmark` action 封装 `vllm bench serve` | 输出 `bench.json` |
| MFU 子系统 | `--enable-mfu-metrics` 通过 `--config` 传递 | 日志中 `perf_metrics` 段 |
| ProfilerConfig | `profile --kind torch` 自动构造 JSON 参数 | 查看 engine log 中注入参数 |

---

## 2. 脚本修改清单

### 2.1 修改文件

**文件**: `scripts/manage-container.sh`

### 2.2 修改汇总

| # | 修改内容 | 位置 | 行数 | 说明 |
|---|---------|------|------|------|
| 1 | 新增 benchmark 默认值 | DEFAULT_* 段 | 8 行 | 8 个 `BENCH_*` 变量 |
| 2 | 新增 resolve_config 解析 | resolve_config() | 8 行 | 8 个 `VLLM_BENCH_*` 映射 |
| 3 | 新增 save_state 持久化 | save_state() | 2 行 | 8 个 key 加入持久化列表 |
| 4 | 更新 usage() 帮助 | usage() | 15 行 | action 列表 + flags + examples |
| 5 | 修复 parse_args --help | parse_args() | 5 行 | action 专属 help 修复 |
| 6 | 新增 cmd_benchmark() | 新函数 | ~165 行 | benchmark 完整实现 |
| 7 | 更新 main() 路由 | main() | 1 行 | benchmark → cmd_benchmark |
| 8 | 增强 profile_engine() npu-smi | profile_engine() | ~20 行 | 循环内采集 npu 指标 |
| 9 | 增强 profile_msprof() TraceLoom | profile_msprof() | 16 行 | 完成后自动分析 |
| 10 | 更新 cmd_config JSON 输出 | cmd_config() | 6 行 | 新增 benchmark 配置字段 |

### 2.3 代码变更总览

```diff
- 新增 ~225 行代码
- 修改 ~15 行现有代码
- 删除 0 行
- 完全向后兼容
```

---

## 3. 架构设计

### 3.1 模块依赖关系

```
manage-container.sh
├── parse_args()          → CLI 参数解析，修复 --help 路由
├── resolve_config()      → 4 级配置优先级 + BENCH_* 变量
├── save_state()          → 持久化非敏感配置
├── activate_envs()       → conda + ascend 环境激活
├── require_api_key()     → API key 校验
│
├── cmd_start()           → 启动 engine
├── cmd_stop()            → 停止 engine
├── cmd_benchmark()       → [新增] 在线服务基准测试
│   ├── 参数解析
│   ├── 数据集校验
│   ├── vllm bench serve 执行
│   ├── summary 生成
│   └── 终端输出关键指标
│
├── cmd_profile()
│   ├── profile_engine()  → [增强] 新增 npu-smi 采集
│   ├── profile_torch()   → 不变
│   └── profile_msprof()  → [增强] 新增 TraceLoom 自动分析
│
└── main()                → [更新] benchmark 路由
```

### 3.2 配置优先级（不变）

```
CLI --config > state.env > --profile > env > 内置默认值
```

---

## 4. 使用方式

### 4.1 快速入门

```bash
# 1. 启动 engine
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh start

# 2. 快速健康检查（L1）
VLLM_HUST_API_KEY=testkey123 \
bash scripts/manage-container.sh profile --kind engine \
  --label smoke --duration 20 --interval 2 --traffic-requests 10

# 3. 服务级基准测试（L2）
VLLM_HUST_API_KEY=testkey123 \
bash scripts/manage-container.sh benchmark \
  --label quick-bench --num-prompts 200 --concurrency 8

# 4. 框架级 Profiling（L3）
VLLM_HUST_API_KEY=testkey123 \
bash scripts/manage-container.sh profile --kind torch \
  --label torch-test --requests 8

# 5. 硬件级 Profiling（L4，需先 stop engine）
bash scripts/manage-container.sh stop

VLLM_HUST_API_KEY=testkey123 \
bash scripts/manage-container.sh profile --kind msprof \
  --label msprof-test --duration 30 --requests 16

# 6. 恢复 engine
VLLM_HUST_API_KEY=testkey123 \
bash scripts/manage-container.sh start
```

### 4.2 benchmark 命令参考

```bash
# 基本用法（默认 200 请求，random 数据集）
bash scripts/manage-container.sh benchmark

# 完整参数
bash scripts/manage-container.sh benchmark \
  --label my-test            # 结果目录标签
  --num-prompts 500          # 请求数
  --concurrency 16           # 最大并发数
  --rate inf                 # 请求速率（inf=全速）
  --input-len 128            # 输入长度（random 数据集）
  --output-len 64            # 输出 token 数
  --dataset random           # 数据集类型
  --dataset-path /data/x.jsonl  # 数据集路径（sonnet/sharegpt 必须）
  --backend vllm             # 后端类型

# 真实数据集测试
bash scripts/manage-container.sh benchmark \
  --label sharegpt \
  --dataset sharegpt \
  --dataset-path /data/sharegpt.jsonl \
  --num-prompts 200 \
  --rate 2 \
  --concurrency 8

# 节流测试
bash scripts/manage-container.sh benchmark \
  --label rate-limited \
  --num-prompts 300 \
  --rate 10 \
  --concurrency 32
```

### 4.3 组合测试场景

```bash
# 场景：完整性能评估（benchmark + engine profile 同时运行）
# Step 1: 启动 engine
VLLM_HUST_API_KEY=testkey123 bash scripts/manage-container.sh start

# Step 2: 后台运行 benchmark
bash scripts/manage-container.sh benchmark \
  --label full-eval --num-prompts 500 --concurrency 16 &
BENCH_PID=$!

# Step 3: 同时采集 engine 指标
bash scripts/manage-container.sh profile --kind engine \
  --label full-eval-metrics --duration 120 --interval 2

wait $BENCH_PID

# Step 4: 查看结果
echo "Benchmark results:"
ls /tmp/vllm-hust-manager/profile/benchmark/full-eval-*/
echo "Metrics results:"
ls /tmp/vllm-hust-manager/profile/engine/full-eval-metrics-*/
```

### 4.4 profile 命令详解（来自 manage-container.md）

本节详细说明 3 种 profile 模式的具体命令、预期输出和产物解读。

#### P3 — profile --kind engine（Prometheus 快照）

```bash
# 基础（无流量，抓 idle engine 指标）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label engine-smoke --duration 8 --interval 2
```

预期：4 个 `NNNN-HHMMSS.prom` 快照（每 ~2s 一个），`failed: 0`，`summary.txt` 摘出关键 `vllm:*` 指标。

**带流量（让 metrics 真正动起来）：**

```bash
# urllib 后端（零依赖）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label engine-load --duration 30 --interval 2 \
    --traffic-requests 30 --traffic-concurrency 4

# bench 后端（更可靠，适合大负载）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label engine-bench --duration 30 --interval 2 \
    --traffic-requests 30 --traffic-concurrency 4 --traffic-backend bench \
    --traffic-input-len 128 --traffic-dataset random
```

**traffic generator flags：**

| flag | 说明 | 默认值 |
|------|------|--------|
| `--traffic-backend <b>` | `urllib` \| `bench` | `urllib` |
| `--traffic-requests N` | 期间发 N 个请求 | `0`（不发） |
| `--traffic-concurrency C` | 并发数 | `4` |
| `--traffic-rate R` | 节流 R req/s（`0`=全速） | `0` |
| `--traffic-max-tokens N` | 每请求最大 token | `64` |
| `--traffic-input-len N` | 输入长度（bench 后端） | `128` |
| `--traffic-dataset <d>` | `random` \| `sonnet` \| `sharegpt` | `random` |
| `--traffic-dataset-path <p>` | sonnet/sharegpt 本地路径 | — |

#### P4 — profile --kind torch（PyTorch profiler）

```bash
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind torch \
    --label torch-smoke --requests 3
```

预期：
- engine healthy in ~60s
- `POST /start_profile` → 200，发 3 个 chat 请求 → `chat: ok=3 fail=0`
- `POST /stop_profile` → 200
- 1 个 `train05_<pid>.async_llm.<ts>.pt.trace.json.gz`（~1.5 MB）+ 1 个 `rank*_<pid>_<ts>_ascend_pt/` 目录（CANN 原始 trace）
- 测完自动 stop profile-mode engine 并恢复原 engine（除非 `--keep-engine-running`）
- `chrome://tracing` → Load → 选 `*.pt.trace.json.gz` 可视化

**torch flags：**

| flag | 说明 | 默认值 |
|------|------|--------|
| `--requests N` | 期间发的 chat 请求数 | `8` |
| `--with-stack / --no-stack` | 是否带 stack trace | `with` |
| `--keep-engine-running` | 测完不自动恢复原 engine | 关闭 |
| `--no-autostart` | 引擎没起时不要自动 start | 关闭 |

#### P5 — profile --kind msprof（CANN kernel profiler）

> **独占 NPU**：msprof 必须独占 NPU 和 port；跑前先 `bash scripts/manage-container.sh stop`。

```bash
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind msprof \
    --label msprof-smoke --duration 12 --requests 3 \
    --config VLLM_ENGINE_PORT=18105 \
    --config VLLM_ENGINE_NPU_DEVICES=3 \
    --config ASCEND_RT_VISIBLE_DEVICES=3 \
    --config ASCEND_VISIBLE_DEVICES=3
```

预期：
- engine healthy in ~60s
- 3 个 chat request 全部 ok（`chat: ok=3 fail=0`）
- msprof `--duration` 到点自动停 + 5s 收尾 + SIGTERM 兜底
- 自动 export 出：
  - `PROF_<id>/mindstudio_profiler_output/op_summary_<ts>.csv`（~13 MB）
  - `PROF_<id>/mindstudio_profiler_output/task_time_<ts>.csv`（~5.5 MB）
  - `PROF_<id>/mindstudio_profiler_output/op_statistic_<ts>.csv` + `api_statistic_<ts>.csv`
  - `PROF_<id>/mindstudio_profiler_output/msprof_<ts>.json`（~126 MB）
- `summary.txt` 记录 `prof_dir` 路径，用 **MindStudio Insight** → Import Project 选 `PROF_*` 目录可视化

**msprof flags：**

| flag | 说明 | 默认值 |
|------|------|--------|
| `--duration <sec>` | 采集时长 | `30s` |
| `--requests N` | 期间发的 chat 请求数 | `8` |
| `--aic-metrics <list>` | `\|` 分隔的 aic metrics | （空） |
| `--task-memory on\|off` | `--task-memory=` 参数 | `off` |
| `--sys-profiling on\|off` | `--sys-profiling=` 参数 | `off` |
| `--msprof-bin <path>` | 覆盖 msprof 路径 | 自动检测 |

合法 `--aic-metrics` 值：`ArithmeticUtilization` \| `PipeUtilization` \| `Memory` \| `MemoryL0` \| `MemoryUB` \| `L2Cache` \| `ResourceConflictRatio` \| `MemoryAccess`

**注意**：`msprof` 不支持 `--no-autostart`（它必须自己 fork vllm）。

### 4.5 一次性跑 P3 + P4 + P5

```bash
SCRIPT=scripts/manage-container.sh
PROFILE=profiles/inplace-qwen2.5-0.5b-npu1.env
export VLLM_HUST_API_KEY=testkey123
export VLLM_ENGINE_PORT=18105
export VLLM_ENGINE_NPU_DEVICES=3
export ASCEND_RT_VISIBLE_DEVICES=3
export ASCEND_VISIBLE_DEVICES=3

bash $SCRIPT stop || true
bash $SCRIPT start --profile "$PROFILE"
bash $SCRIPT profile --kind engine --label p3 --duration 8 --interval 2
bash $SCRIPT profile --kind torch  --label p4 --requests 3
bash $SCRIPT stop
bash $SCRIPT profile --kind msprof --label p5 --duration 12 --requests 3
```

### 4.6 profile --kind engine 带流量生成器详解

#### 两种 traffic 后端

| 后端 | flag | 客户端 | 优点 | 限制 |
| --- | --- | --- | --- | --- |
| `urllib`（默认） | `--traffic-backend urllib` | Python `urllib.request` | 零依赖，不需 model 文件 | vllm-hust keep-alive 偶发挂死；并发 >8 时可能部分请求 hang |
| `bench` | `--traffic-backend bench` | `vllm bench serve`（aiohttp） | 30 req 0 fail；标准 bench 工具；输出 TTFT/TPOT/ITL percentile | 需要 model 文件在磁盘上（加载 tokenizer）；需 conda env |

**bench 后端**会在模型文件不存在时**自动降级到 urllib**并打印警告。

#### urllib 后端示例

```bash
# 随机文本压测
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label bench-vs-random --duration 30 --interval 2 \
    --traffic-backend bench \
    --traffic-requests 60 --traffic-concurrency 8 --traffic-rate 0 \
    --traffic-max-tokens 128 \
    --traffic-dataset random --traffic-input-len 550

# sonnet 真实文本
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label bench-sonnet --duration 30 --interval 2 \
    --traffic-requests 60 --traffic-concurrency 8 --traffic-rate 0 \
    --traffic-backend bench --traffic-dataset sonnet

# sharegpt chat 真实 workload
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label bench-sharegpt --duration 30 --interval 2 \
    --traffic-requests 100 --traffic-concurrency 16 --traffic-rate 0 \
    --traffic-backend bench --traffic-dataset sharegpt
```

#### summary.txt 产物

summary 自动包含三段（视后端而定）：

1. **traffic / bench result** — throughput、latency p50/p90/p99、in/out tok/s
2. **metrics delta (snap 1 → final)** — profile 期间 counter 的变化量：

   ```
   --- metrics delta (snap 1 → final) ---
     prompt_tokens_total            3968 → 4360  (+392)
     generation_tokens_total         992 → 1120  (+128)
     request_success{length}           31 → 39    (+8)
     e2e_latency_count                 31 → 39    (+8)
   ```

   差值应与 traffic log 的 in_tokens / out_tokens / 请求数一致。
3. **last snapshot: key vllm:\* metrics** — final 时刻的绝对值

---

## 5. 输出目录结构

```
/tmp/vllm-hust-manager/
├── engine.pid
├── engine.log
├── manager.log
├── state.env
└── profile/
    ├── benchmark/              # benchmark action 结果
    │   └── <label>-<ts>/
    │       ├── bench.json      # vllm bench serve 输出
    │       ├── bench.log       # 原始日志
    │       └── summary.txt     # 摘要
    ├── engine/                 # profile --kind engine 结果
    │   └── <label>-<ts>/
    │       ├── *.prom          # Prometheus 快照
    │       ├── npu-smi.csv     # NPU 硬件指标（温度/功耗/利用率/HBM）
    │       ├── traffic.log     # 流量生成器日志
    │       └── summary.txt     # 摘要（含 metrics delta）
    ├── torch/                  # profile --kind torch 结果
    │   └── <label>-<ts>/
    │       ├── *.pt.trace.json.gz  # PyTorch Profiler 输出
    │       ├── summary.txt     # 摘要
    │       └── cfg.env         # 备份的 engine 配置
    └── msprof/                 # profile --kind msprof 结果
        └── <label>-<ts>/
            ├── PROF_<id>_<ts>_<hash>/   # CANN msprof 原始输出
            │   ├── device_<n>/  sqlite/*.db  sample.json
            │   ├── host/        sqlite/*.db  info.json
            │   └── mindstudio_profiler_output/
            │       ├── op_summary_<ts>.csv      # 算子耗时汇总（~13 MB）
            │       ├── task_time_<ts>.csv       # 任务时间分布（~5.5 MB）
            │       ├── op_statistic_<ts>.csv    # 算子统计
            │       ├── api_statistic_<ts>.csv   # API 调用统计
            │       └── msprof_<ts>.json         # 完整 profiling 数据（~126 MB）
            ├── traceloom/      # TraceLoom 自动分析结果
            │   ├── summary.md
            │   ├── *.anchor.tree.readable.md
            │   └── *.csv
            ├── summary.txt     # 摘要
            └── export.log      # msprof --export 日志

可通过 `--config VLLM_PROFILE_OUTPUT_DIR=/custom/path` 覆盖根路径。

---

## 6. 环境变量参考

### 6.1 Benchmark 配置

| 环境变量 | CLI flag | 默认值 | 说明 |
|---------|---------|--------|------|
| `VLLM_BENCH_NUM_PROMPTS` | `--num-prompts` | 200 | 请求数 |
| `VLLM_BENCH_CONCURRENCY` | `--concurrency` | 8 | 最大并发数 |
| `VLLM_BENCH_RATE` | `--rate` | inf | 请求速率 |
| `VLLM_BENCH_INPUT_LEN` | `--input-len` | 128 | 输入长度 |
| `VLLM_BENCH_OUTPUT_LEN` | `--output-len` | 64 | 输出长度 |
| `VLLM_BENCH_DATASET` | `--dataset` | random | 数据集类型 |
| `VLLM_BENCH_DATASET_PATH` | `--dataset-path` | (空) | 数据集路径 |
| `VLLM_BENCH_BACKEND` | `--backend` | vllm | 后端类型 |

### 6.2 增强的 Profile 配置

| 环境变量 | 影响 | 说明 |
|---------|------|------|
| `VLLM_PROFILE_OUTPUT_DIR` | 所有 profile/benchmark | 输出根目录 |
| `VLLM_PROFILE_LABEL` | 所有 profile/benchmark | 默认标签 |

---

## 7. 兼容性保证

### 7.1 现有功能不受影响

- `start/stop/restart/status/health/logs/config/foreground` — 完全不变
- `profile --kind engine|torch|msprof` — 行为增强，不破坏现有接口
- 所有现有 `--config KEY=VALUE` 用法不变
- `state.env` 格式不变，新增字段向后兼容

### 7.2 已知限制

- `benchmark` 依赖 `vllm bench serve` 命令，需要 conda 环境中安装 vllm
- `benchmark` 需要 engine 在运行（或 `AUTOSTART=1`）
- sonnet/sharegpt 数据集需要本地文件路径

---

## 8. 验证方法

### 8.1 语法检查

```bash
bash -n scripts/manage-container.sh && echo "SYNTAX OK"
```

### 8.2 帮助输出

```bash
# 全局帮助
bash scripts/manage-container.sh --help

# action 专属帮助
bash scripts/manage-container.sh benchmark --help
bash scripts/manage-container.sh profile --help
bash scripts/manage-container.sh profile --kind engine --help
```

### 8.3 配置输出

```bash
bash scripts/manage-container.sh config --json | grep bench
# 应输出:
#   "bench_num_prompts": 200,
#   "bench_concurrency": 8,
#   ...
```

### 8.4 功能测试（需 NPU 环境）

```bash
# 1. 启动 engine
VLLM_HUST_API_KEY=testkey123 bash scripts/manage-container.sh start

# 2. 引擎状态检查
bash scripts/manage-container.sh status

# 3. 执行 benchmark
bash scripts/manage-container.sh benchmark \
  --label test-run --num-prompts 10 --concurrency 2

# 4. 验证输出
ls -la /tmp/vllm-hust-manager/profile/benchmark/test-run-*/
cat /tmp/vllm-hust-manager/profile/benchmark/test-run-*/summary.txt

# 5. 停止 engine
bash scripts/manage-container.sh stop
```

---

## 9. 维护指南

### 9.1 新增 benchmark 参数

1. 在 `DEFAULT_*` 段新增默认值
2. 在 `resolve_config()` 新增 `VLLM_BENCH_*` 映射
3. 在 `cmd_benchmark()` 的 `case` 块新增 flag 解析
4. 在 `save_state()` 的 key 列表新增
5. 在 `usage()` 和 `cmd_benchmark --help` 更新文档
6. 在 `cmd_config()` JSON 输出新增字段

### 9.2 新增 profile 种类

1. 遵循现有 `profile_engine()` / `profile_torch()` / `profile_msprof()` 模式
2. 在 `cmd_profile()` 的 `case "$kind"` 块新增分支
3. 在 `usage()` 更新帮助

### 9.3 回滚方案

```bash
# 回滚到原始版本
git checkout HEAD~1 -- scripts/manage-container.sh

# 或只恢复特定变更
git diff HEAD~1 -- scripts/manage-container.sh | git apply -R
```

---

## 10. 附录：与五层测试体系的对应关系

| 测试场景 | 命令 | 覆盖层 | 耗时 |
|---------|------|--------|------|
| 快速健康检查 | `profile --kind engine --traffic-requests 10` | L1 | ~30s |
| 标准在线服务测试 | `benchmark --num-prompts 500 --concurrency 16` | L2 | ~5min |
| 算子级性能分析 | `profile --kind torch --requests 8` | L3 | ~3min |
| 硬件级深度分析 | `profile --kind msprof --duration 30` | L4 | ~2min |
| 长稳测试 | 循环执行 benchmark | L5 | ≥1h |
| 组合测试 | benchmark + profile engine 同时 | L1+L2+L5 | 自定义 |

---

## 11. profile 数据解读指南

### 11.1 profile / bench 的 4 个视角

"profile 过程"在 vllm-hust 上是**多个工具一起用**得到一个负载下的完整画像，每个工具回答不同的问题。manage-container.sh 自身覆盖 3 个 (engine / torch / msprof)，第 4 个 (bench) 通过 `benchmark` action 提供。

| 视角 | 工具 | 产物 | 回答的问题 |
| --- | --- | --- | --- |
| **bench (client 视角)** | `benchmark` action | `bench.json` + 终端 summary | 每个请求的真实 TTFT / TPOT / ITL + percentile + 端到端 throughput |
| **engine (server counters)** | `profile --kind engine` | `NNNN-HHMMSS.prom` + `summary.txt` | vllm 内部累计 counters（已用 token / KV / batch 大小 / finish reason） |
| **torch (Python + torch op)** | `profile --kind torch` | `*.pt.trace.json.gz` + `rank*_ascend_pt/` | python 调用栈 + torch op 时间 + NPU kernel launch timeline（chrome://tracing） |
| **msprof (NPU kernel 级)** | `profile --kind msprof` | `PROF_*/mindstudio_profiler_output/*.csv` + `msprof_*.json` | aic metrics (ArithmeticUtilization / PipeUtilization / Memory / L2Cache) + 逐 kernel 时间 |

### 11.2 把 profile 数据"读"成结论

一次完整 profile 跑出来的产物，按下列顺序看：

1. **`summary.txt` 关键指标 + `traffic.log` / bench.json** — 一眼看吞吐 / 延迟是否合理
2. **`*.prom` 间隔对比** — 把 idle 快照 vs 加载中快照 vs final 快照的 diff 拿出来：
   - `prompt_tokens_total` 差值 = 真实处理的 prompt tok 数（验证请求真到 engine）
   - `generation_tokens_total` 差值 = 真实生成的 tok 数
   - `request_success_total{finished_reason="length"}` 增长 = 截断（max_tokens 不够）
   - `request_success_total{finished_reason="error"}` 增长 = 出错（看 engine.log）
3. **`*.pt.trace.json.gz`（torch）** — chrome://tracing 打开，看 python 主线程 / torch op / NPU kernel 三段时间，看是不是有"空档"（idle gap）
4. **`PROF_*/op_summary.csv`（msprof）** — 按 `Type` 排序，看哪些 kernel 占时间最多：
   - `CONV` / `Matmul` / `FlashAttentionScore` — 计算密集
   - `Malloc` / `Memcpy` / `DataTransfer` — 数据搬运开销
   - 通过 `PipeUtilization` 看出 aic pipeline 利用率
5. **跨工具交叉验证**：
   - bench 报的 `mean_ttft_ms` ≈ torch trace 里 `1st-token` 之前的 python+launch 时间
   - bench 报的 `mean_tpot_ms` ≈ msprof 里 decode 阶段 kernel 时间 / 1
   - engine `generation_tokens_total` 差值 / bench duration ≈ engine 视角的 output tok/s，应该和 bench 报的数字一致（误差 < 5%）

### 11.3 bench.json 字段解读

| 字段 | 含义 | 期望区间（Qwen2.5-0.5B eager, max-num-seqs=8）|
| --- | --- | --- |
| `mean_ttft_ms` / `p99_ttft_ms` | prompt 提交到第一个 token 出来 | < 200ms（短 prompt）|
| `mean_tpot_ms` / `p99_tpot_ms` | 每 token decode 延迟（不含 1st）| 30-50ms（0.5B 短 batch）|
| `mean_itl_ms` | inter-token latency | 跟 TPOT 接近（无流式 chunking）|
| `output_throughput` (tok/s) | generation 端总吞吐 | 80-200 tok/s (0.5B 1卡)|
| `total_token_throughput` (tok/s) | prompt+gen 加权 | 400-500 tok/s（prompt 占大头）|
| `request_throughput` (req/s) | 请求级吞吐 | concurrency / mean_latency |
| `max_concurrent_requests` | 实际峰值并发 | 4 (设 max_concurrency=4 时)|

---

## 12. profile 已知陷阱

### 12.1 NPU 0 内存被占

之前调试时杀掉的 EngineCore 进程可能没完全释放 NPU HBM。`npu-smi info` 看 `Memory-Usage(MB)`，如果某个 NPU 显示 > 50 GB 但没有相关 PID，需要切到空闲 NPU（2-7）或者重启容器。用 `--config VLLM_ENGINE_NPU_DEVICES=<其他>` 切换。

### 12.2 msprof 独占 NPU

msprof 必须独占 NPU，跑前必须 `bash scripts/manage-container.sh stop` 停掉任何占用 NPU 的 vllm / msprof 实例。脚本会检测端口冲突（msprof 失败模式之一）并 abort。

### 12.3 msprof --aic-metrics 是单值

msprof CLI 不接受 `,` 分隔串，必须重复传多个 flag。脚本在 `build_msprof_command` 里把 `|` / `,` 分隔的输入展开为多个 `--aic-metrics=X`。

### 12.4 msprof 强杀后导出

msprof `--duration` 到点不保证 100% 优雅退出；脚本在 `kill -TERM` 后多等 5s 再 `pkill -9 -f "VLLM::EngineCore"`，避免 EngineCore 占 NPU 内存导致下次 start 失败。

### 12.5 keep-alive 偶发挂死（urllib 后端）

并发请求里第一批 4-8 个能完成，后续 client 端 `r.read()` 阻塞（vllm 端日志已 200 OK）。脚本做了 `Connection: close` + 30s per-req timeout + deadline 兜底，但 100% N 个跑不完。实操上 8 个并发 + `max_tokens=16` 是稳的。

**bench 后端不踩这个坑**：bench 内部用 aiohttp 客户端行为不同，30 req 0 fail。所以**真要测大负载**用 `--traffic-backend bench` 更可靠。

### 12.6 `--profiler-config` 启动对 NPU 内存更敏感

带 profiler 启动的 engine 似乎在 NPU 0 HBM 已被其他 session 占满时直接 ValueError（不是 out-of-memory，而是"free memory < GPU memory utilization target"）。如果 NPU 0 不可用，先 `npu-smi info` 找空闲卡，再用 `--config VLLM_ENGINE_NPU_DEVICES=<n> --config ASCEND_RT_VISIBLE_DEVICES=<n>` 切过去。

### 12.7 profile_torch 测完自动恢复原 engine

`profile_torch` 测完默认会调 `cmd_start` 恢复"原 engine"。但 CLI `--config` 覆盖不写进 `state.env`（避免 secret 污染 + 保留动态性），所以脚本额外维护一份 `state.env.torch-cfg-bak`，把当时生效的关键 env 备份到 `cfg_bak` + 归档一份到 out_dir 的 `cfg.env`。恢复时用 `set -a; source cfg_bak; cmd_start` 注入 cfg。

- 想测完不自动恢复：传 `--keep-engine-running`
- 想看测时 env：打开 `<out_dir>/cfg.env`