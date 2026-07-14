# manage-container.sh — 容器内 vLLM-HUST 服务管理器

`scripts/manage-container.sh` 是 `manage.sh` 的"容器内直跑"版本，不依赖 `docker` / `systemd`，直接
`conda activate` + `source ascend env` + `exec vllm serve`。所有 `manage.sh` 的高频动作（start /
stop / restart / status / health / logs / config / foreground）都对应到一个子命令，profile 提供三种
采集模式（engine / torch / msprof）。

## 快速上手

```bash
# 1) 启动（必传 API key；profile 文件可选）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh start \
    --profile profiles/inplace-qwen2.5-0.5b-npu1.env

# 2) 查状态
bash scripts/manage-container.sh status

# 3) 看日志
bash scripts/manage-container.sh logs

# 4) 停
bash scripts/manage-container.sh stop
```

> 容器内 `/usr/bin/curl` 因 LD_LIBRARY_PATH 冲突（`libldap.so.2: undefined symbol: EVP_md2`）在
> 失败时也返回 0，会让 health/metrics 探针假阳性。脚本所有 HTTP 探测统一走 `python3 + urllib.request`，
> 见 [scripts/manage-container.sh](../scripts/manage-container.sh) `wait_for_health`。
>
> **API key（`VLLM_HUST_API_KEY`）规则**：
> - **需要** 的 action：`start` / `foreground` / `profile --kind torch` / `profile --kind msprof`
>   （这些会调外部 HTTP API 或把 key 透传给 vllm serve）
> - **不需要** 的 action：`stop` / `restart` / `status` / `health` / `logs` / `config` /
>   `profile --kind engine`（`/metrics` 公开）
> - 取值：任意非空字符串（不是字面量 `EMPTY`），常用 `testkey123` 即可
> - 生命周期：state.env **故意不写**（敏感数据），每个新 shell session 都要重新 `export`

## 子命令一览（v0.2）

| 子命令 | 说明 |
|---|---|
| `start` | 后台启动 vllm serve（写 pid/log，state.env，自动等 /health） |
| `stop` | 优雅停（SIGTERM 10s → SIGKILL） |
| `restart` | stop + start |
| `status` | 进程 / 端口 / 模型 / NPU 摘要（支持 `--json`） |
| `health` | 探活 /health（`--json` 返回 200/000） |
| `logs` | `tail -f` engine log |
| `config` | 打印最终生效配置 |
| `foreground` | 前台启动（调试用） |
| `profile --kind engine` | 周期性抓 /metrics，生成 Prometheus 快照 |
| `profile --kind torch` | vllm 内置 PyTorch profiler（*.pt.trace.json.gz） |
| `profile --kind msprof` | CANN msprof（kernel 级，PROF_*/ 目录） |
| `help` | 显示完整帮助 |

`benchmark` 计划在 P2 实现。

## 公共 flags

| flag | 说明 |
|---|---|
| `--profile <path>` | profile 文件路径（覆盖 `$VLLM_ENGINE_ENV_FILE`） |
| `--config KEY=VALUE` | 单点覆盖（**可重复传**） |
| `--json` | status / health / config 输出 JSON |
| `--no-color` | 关颜色 |
| `-h`, `--help` | 帮助 |

`--config` 一次只接一个 KV，要传多个请重复：

```bash
bash scripts/manage-container.sh start \
  --profile profiles/inplace-qwen2.5-0.5b-npu1.env \
  --config VLLM_ENGINE_PORT=18105 \
  --config VLLM_ENGINE_NPU_DEVICES=3 \
  --config ASCEND_RT_VISIBLE_DEVICES=3
```

## 配置优先级

CLI `--config` > `state.env`（start 时落盘） > `--profile` 文件 > 进程环境 > `./profiles/default.env`
> 内置默认。

`state.env` 在每次 `start` 时落盘，记录 **start 时** 解析出的所有非 secret 配置。`status` / `health` /
`stop` / `restart` 都会优先复用 `state.env`，所以即使后续改了环境变量，也能保证用一致的配置关掉 engine。

> `state.env` 故意不写 `*KEY*` / `*TOKEN*` / `*SECRET*` 类的变量。Secret 一律走
> `VLLM_HUST_API_KEY` 环境变量。

## Profile 文件

profile 文件是 `KEY=VALUE` 形式的 dotenv。最简示例
[profiles/inplace-qwen2.5-0.5b-npu1.env](../profiles/inplace-qwen2.5-0.5b-npu1.env) 包含：

- 模型路径、served name、port、NPU
- 调度参数（max-model-len、max-num-seqs、gpu-memory-utilization）
- 优化开关（prefix-caching、chunked-prefill、enforce-eager）
- Ascend 相关（plugins、ascend-visible-devices、torch-npu-alloc-conf）

不带 secret。要换 NPU / 端口 / 模型，覆盖同名 `VLLM_ENGINE_*` 即可（profile 文件 + `--config` 都可）。

## Usage — 典型命令（已验证）

以下命令在 Ascend 910B × 8、`vllm-hust-dev` conda env、`/tmp/vllm-hust-manager` 为日志目录的
容器内实跑通过。统一用 [profiles/inplace-qwen2.5-0.5b-npu1.env](../profiles/inplace-qwen2.5-0.5b-npu1.env)；
NPU 0 上次未释放的 HBM 占用较多，所以用 `NPU 3` + `port 18105` 避让。改 NPU 时同时覆盖
`VLLM_ENGINE_NPU_DEVICES` / `ASCEND_RT_VISIBLE_DEVICES` / `ASCEND_VISIBLE_DEVICES` 三个。

### P1 — 基础管理

```bash
# start（首次跑 profile/torch 前要先 start）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh start \
    --profile profiles/inplace-qwen2.5-0.5b-npu1.env \
    --config VLLM_ENGINE_PORT=18105 \
    --config VLLM_ENGINE_NPU_DEVICES=3 \
    --config ASCEND_RT_VISIBLE_DEVICES=3 \
    --config ASCEND_VISIBLE_DEVICES=3

# 查 / 看
bash scripts/manage-container.sh status
bash scripts/manage-container.sh health
bash scripts/manage-container.sh config        # 打印最终生效配置
bash scripts/manage-container.sh logs          # tail -f engine.log

# 停
bash scripts/manage-container.sh stop
```

### P3 — profile --kind engine

```bash
# engine 已经在跑（start 之后）；抓 8s Prometheus 快照，间隔 2s
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label engine-smoke --duration 8 --interval 2
```

预期：4 个 `NNNN-HHMMSS.prom` 快照（每 ~2s 一个），`failed: 0`，`summary.txt` 摘出关键
`vllm:*` 指标。

### P4 — profile --kind torch（PyTorch profiler）

```bash
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind torch \
    --label torch-smoke --requests 3
```

预期：
- engine healthy in ~60s
- `POST /start_profile` → 200，发 3 个 chat 请求 → `chat: ok=3 fail=0`
- `POST /stop_profile` → 200
- 1 个 `train05_<pid>.async_llm.<ts>.pt.trace.json.gz`（~1.5 MB）+ 1 个
  `rank*_<pid>_<ts>_ascend_pt/` 目录（CANN 原始 trace）
- 测完自动 stop profile-mode engine 并恢复原 engine（除非 `--keep-engine-running`）
- `chrome://tracing` → Load → 选 `*.pt.trace.json.gz` 可视化

### P5 — profile --kind msprof（CANN kernel profiler）

> msprof 必须独占 NPU 和 port；跑前先 `bash scripts/manage-container.sh stop`。

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

### 一次性跑 P3 + P4 + P5

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

## profile --kind engine

周期性抓 vllm `/metrics`（Prometheus 文本格式），落盘成 `NNNN-HHMMSS.prom` 快照，结束时输出
`summary.txt` 摘出关键 `vllm:*` 指标。

### 基础（无流量）

```bash
bash scripts/manage-container.sh profile --kind engine \
  --label engine-smoke --duration 30 --interval 2
```

输出：

```
profile/engine/engine-smoke-<ts>/
  0001-103526.prom  (50283 bytes)
  0002-103528.prom
  ...
  summary.txt
```

### 带 traffic generator（让 metrics 真正动起来）

idle engine 的 counters 默认全 0（vllm 进程不持久历史），看不出 schedule / batch / KV cache
行为。`--traffic-*` 系列 flag 在 profile 期间并发发 chat 请求，metrics 就会从 0 增长，从而
能区分 idle vs load 下的差异。

不带 `--traffic-*` 时会打印 idle 警告：

```
[WARN] no traffic configured — metrics will reflect idle engine.
       Add --traffic-requests 30 to capture load-time metrics.
```

#### 两种 traffic 后端

| 后端 | flag | 客户端 | 优点 | 限制 |
| --- | --- | --- | --- | --- |
| `urllib`（默认） | `--traffic-backend urllib` | Python `urllib.request` | 零依赖，不需 model 文件 | vllm-hust keep-alive 偶发挂死；并发 >8 时可能部分请求 hang |
| `bench` | `--traffic-backend bench` | `vllm bench serve`（aiohttp） | 30 req 0 fail；标准 bench 工具；输出 TTFT/TPOT/ITL percentile | 需要 model 文件在磁盘上（加载 tokenizer）；需 conda env |

**bench 后端**会在模型文件不存在时**自动降级到 urllib**并打印警告。

#### urllib 后端示例

```bash
# 16 并发，32 请求（urllib 已知会 hang 在 16+，所以保持 16×16 已经能验高负载）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label my-test-1 --duration 30 --interval 2 \
    --traffic-requests 16 --traffic-concurrency 16 --traffic-rate 0 \
    --traffic-max-tokens 64
```

#### bench 后端示例

```bash
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label engine-bench --duration 30 --interval 2 \
    --traffic-requests 30 --traffic-concurrency 4 --traffic-rate 0 \
    --traffic-max-tokens 32 --traffic-backend bench \
    --traffic-input-len 128 --traffic-dataset random
```

#### flags

| flag | 说明 | urllib | bench |
| --- | --- | --- | --- |
| `--traffic-requests N` | 期间发 N 个请求（`0` = 不发，默认 `0`） | chat 请求 | `--num-prompts N` |
| `--traffic-concurrency C` | 并发数（默认 `4`） | Semaphore(C) | `--max-concurrency C` |
| `--traffic-rate R` | 节流 R req/s（`0` = 全速，默认 `0`） | sleep 到 i/rate | `--request-rate inf/R` |
| `--traffic-prompt "text"` | 请求内容（默认中文 prompt） | chat body | **忽略**（bench 用 dataset） |
| `--traffic-max-tokens N` | 每请求最大 token（默认 `64`） | chat body | `--random-output-len N` |
| `--traffic-backend <b>` | `urllib` \| `bench`（默认 `urllib`） | — | — |
| `--traffic-input-len N` | prompt 输入长度（默认 `128`） | **忽略** | `--random-input-len N` |
| `--traffic-dataset <d>` | `random` \| `sonnet` \| `sharegpt`（默认 `random`） | **忽略** | `--dataset-name <d>` |

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

#### 已知陷阱

- **vllm-hust 上 keep-alive 偶发挂死**（urllib 后端）：并发请求里第一批 4-8 个能完成，
  后续 client 端 `r.read()` 阻塞（vllm 端日志已 200 OK）。脚本做了 `Connection: close` +
  30s per-req timeout + deadline 兜底，但 100% N 个跑不完。实操上 8 个并发 + `max_tokens=16`
  是稳的。
- **bench 后端需要 model 文件在磁盘上**：bench 需要独立加载 tokenizer。如果 model 文件被清理
  （如 HuggingFace cache 被清），bench 会自动降级到 urllib。要让 bench 正常工作，确保
  `MODEL_PATH` 指向的目录存在且包含 `tokenizer_config.json` 等文件。
- **`vllm bench serve` 不踩 keep-alive 挂死**：bench 内部用 aiohttp 客户端行为不同，30 req
  `random 128/32` 跑 10.47s 0 fail。所以**真要测大负载**用 `--traffic-backend bench` 更可靠。
- 多个 profile 跑完会有目录累积，定期 `rm -rf /tmp/vllm-hust-manager/profile/old-*`。

## profile --kind torch（PyTorch profiler）

> 可复制命令见 [P4 Usage](#p4--profile---kind-torchpytorch-profiler)。

通过 `--profiler-config torch_profiler_dir=<out>` 注入配置，启 engine；健康后 `POST /start_profile`，
驱动 N 个 chat 请求，再 `POST /stop_profile`。vllm 落地 `*.pt.trace.json.gz` 文件。
测完会 stop 引擎并恢复 start 前的 state（除非 `--keep-engine-running`）。

flags：

- `--requests N` — 期间发的 chat 请求数（默认 8）
- `--with-stack / --no-stack` — 是否带 stack trace（默认 with）
- `--keep-engine-running` — 测完不自动恢复原 engine
- `--no-autostart` — 引擎没起时不要自动 start（用之前必须手动 `start`）

## profile --kind msprof（CANN kernel profiler）

> 可复制命令见 [P5 Usage](#p5--profile---kind-msprofcann-kernel-profiler)。
> **独占 NPU**：跑前必须先 `stop` 任何占用 NPU 的 vllm / msprof 实例。

msprof 通过 `--application=...` 包住 vllm serve，结束后自动 export 全部数据到 `PROF_*/` 目录。
脚本会检测端口冲突（msprof 失败模式之一）并 abort。

输出（MindStudio Insight 可直接打开）：

```
profile/msprof/msprof-smoke-<ts>/
  PROF_<id>_<ts>_<hash>/
    device_<n>/  sqlite/*.db  sample.json
    host/        sqlite/*.db  info.json
    mindstudio_profiler_output/
      op_summary_<ts>.csv
      task_time_<ts>.csv
      op_statistic_<ts>.csv
      api_statistic_<ts>.csv
      msprof_<ts>.json
    msprof_<ts>.db
  export.log
  summary.txt
```

flags：

- `--duration <sec>` — msprof 采集时长（默认 30s；engine 自动停）
- `--requests N` — 期间发的 chat 请求数
- `--aic-metrics <list>` — `|` 分隔（脚本会展开为多个 `--aic-metrics=...` flag）。合法值：
  `ArithmeticUtilization | PipeUtilization | Memory | MemoryL0 | MemoryUB | L2Cache | ResourceConflictRatio | MemoryAccess`
- `--task-memory on|off` — `--task-memory=` 参数（默认 `off`）
- `--sys-profiling on|off` — `--sys-profiling=` 参数（默认 `off`）
- `--msprof-bin <path>` — 覆盖 msprof 路径（默认 `/usr/local/Ascend/cann-9.0.0/bin/msprof`）

**注意**：`msprof` 不支持 `--no-autostart`（它必须自己 fork vllm）。

## How to run（端到端）

> **本文档是 manage-container.sh 的工具参考**。
> 容器内"vllm-hust 能跑起来"的完整前置步骤（conda / ascend env / NPU / 模型下载）见
> [how-to-run.md](../how-to-run.md)。manage-container.sh **不**做这些 — 它只接管
> "环境已经 ready"之后的 start / stop / profile / bench 流程。
>
> 何时用哪个入口：
>
> | 入口 | 文件 | 适用场景 |
> | --- | --- | --- |
> | **HOST（带 systemd）** | `manage.sh` | 长期服务，systemd 拉起 |
> | **HOST（无 systemd）** | `scripts/launch_ascend_model_service.sh` | 一次性跑，从 HOST dispatch 进容器 |
> | **runtime 容器内（推荐）** | `scripts/manage-container.sh` | 调试 / 一次性验证 / 没 HOST 权限 |
> | 容器内裸 `vllm serve` | （见 [how-to-run.md](../how-to-run.md) §2） | 不想用任何 wrapper |

### 最小端到端路径（4 步）

```bash
# 0) 一次性的环境（容器内新会话开头跑；细节见 how-to-run.md §0）
source /root/miniconda3/etc/profile.d/conda.sh
conda activate vllm-hust-dev
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /usr/local/Ascend/nnal/atb/set_env.sh --cxx_abi=1
export VLLM_PLUGINS=ascend VLLM_TARGET_DEVICE=npu
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export ASCEND_RT_VISIBLE_DEVICES=3 ASCEND_VISIBLE_DEVICES=3
export VLLM_HUST_API_KEY=testkey123

# 1) start
bash scripts/manage-container.sh start \
  --profile profiles/inplace-qwen2.5-0.5b-npu1.env \
  --config VLLM_ENGINE_PORT=18105 --config VLLM_ENGINE_NPU_DEVICES=3
#  → healthy after ~60s

# 2) 连通性（自带 API 调用，importable from python/curl）
bash scripts/manage-container.sh status
bash scripts/manage-container.sh health
curl -s -H "Authorization: Bearer testkey123" \
  http://127.0.0.1:18105/v1/models

# 3) profile 选一种
bash scripts/manage-container.sh profile --kind engine --label p3 --duration 8
bash scripts/manage-container.sh profile --kind torch  --label p4 --requests 3
bash scripts/manage-container.sh stop  # msprof 前必须 stop
bash scripts/manage-container.sh profile --kind msprof --label p5 --duration 12 --requests 3

# 4) stop
bash scripts/manage-container.sh stop
```

### profile 输出位置

```
${LOG_DIR:-/tmp/vllm-hust-manager}/profile/
  engine/<label>-<ts>/
    NNNN-HHMMSS.prom       # Prometheus 快照
    summary.txt            # 关键 vllm:* 指标摘要
  torch/<label>-<ts>/
    train05_<pid>.async_llm.<ts>.pt.trace.json.gz   # ~1.5MB，chrome://tracing 打开
    rank*_<pid>_<ts>_ascend_pt/                      # CANN 原始 trace
    summary.txt
  msprof/<label>-<ts>/
    PROF_<id>_<ts>_<hash>/
      mindstudio_profiler_output/{op_summary,task_time,op_statistic,api_statistic}_<ts>.csv
      mindstudio_profiler_output/msprof_<ts>.json
    summary.txt            # MindStudio Insight 打开路径
```

## 功能检验（v0.2 验证清单）

以下 14 个动作均在本仓库（commit head + 上述修复后）实跑通过。命令格式与 Usage 章节一致：

| # | action / command | 验证结果 | 备注 |
| --- | --- | --- | --- |
| 1 | `help` | ✅ 输出 v0.2.0 usage 13 行 | |
| 2 | `config` | ✅ 17 行有效配置（log_dir / model / port / npu / dtype / 优化开关 等） | 引擎未起也能跑 |
| 3 | `start --profile …` | ✅ `healthy after 56s` | 默认 8000 端口已被占时自动报错（见"已知陷阱 §1"） |
| 4 | `stop` | ✅ SIGTERM 10s → SIGKILL；清理 engine.pid / state.env | engine 未起时 warning |
| 5 | `restart` | ✅ stop + start，`healthy after 56s` | |
| 6 | `status` | ✅ state / port / npu / model / health 摘要 | engine 不在时读 state.env fallback |
| 7 | `status --json` | ✅ 11 字段 JSON | |
| 8 | `health` | ✅ `health ok: http://127.0.0.1:18105/health` | |
| 9 | `health --json` | ✅ `{http_code: "200", ok: true}` | |
| 10 | `logs` | ✅ `tail -f` engine.log | |
| 11 | `foreground` | ✅ 前台启动（timeout 5s 验证语法） | 调试用，不写 pid |
| 12 | `profile --kind engine` | ✅ 3-4 个 NNNN-HHMMSS.prom 快照，0 fail | 8s duration / 2s interval 测 |
| 13 | `profile --kind torch` | ✅ 1×`train05_*.pt.trace.json.gz`（1.5MB）+ ascend_pt 目录，engine 自动恢复 | 3 requests 测 |
| 14 | `profile --kind msprof` | ✅ 完整 `PROF_*/` 目录 + `op_summary.csv` 13MB / `task_time.csv` 5.5MB / `msprof_*.json` 126MB | 12s duration / 2 requests 测 |

### 验证过程中发现并修复的 bug

| bug | 现象 | 修复 |
| --- | --- | --- |
| `port_in_use` 在 ss/netstat 缺失时永远返回真 | 容器内 `command -v ss` 失败（conda env 改 PATH），netstat fallback `\|\| return 1` 把 `return 1` 当成"port in use"，导致 start 报"port 8000 is in use"但实际空闲 | `port_in_use` 改用 `python3 + socket` 显式 try/except；缺失工具时返回 false（兜底） |
| API_KEY 全局校验拦 status / health / config / logs | `resolve_config` 内做 `[[ -z API_KEY \|\| API_KEY == EMPTY ]] && { exit 1; }`，**所有** action 都走 resolve_config，导致纯查询命令也要求 secret | 改用 `require_api_key` 函数（`if/then/else` 形式避免 `set -e` 跟 `&&` 短路冲突），只在真正调外部 HTTP 的 action 调用（`start` / `foreground` / `profile --kind torch` / `profile --kind msprof`） |

### 没在这次验证里的事项

- `benchmark` action — **v0.2 未实现**（P2 plan），目前用 `how-to-run.md §5` 的 `vllm bench serve` 临时
- profile `--kind torch` 的 `--keep-engine-running` / `--no-autostart` flag — 已实现但未单独回归
- 多卡 TP — profile / 基础管理都支持（`VLLM_ENGINE_TP_SIZE` + `ASCEND_VISIBLE_DEVICES=0,1,2,3`），但这次没在 4/8 卡上验

## profile / bench 的 4 个视角

"profile 过程"在 vllm-hust 上是**多个工具一起用**得到一个负载下的完整画像，每个工具
回答不同的问题。manage-container.sh 自身只覆盖 3 个 (engine / torch / msprof)，第 4 个
(bench) 用 `vllm bench serve` 临时。

| 视角 | 工具 | 产物 | 回答的问题 | 实测数字（Qwen2.5-0.5B / NPU 0 / port 8001）|
| --- | --- | --- | --- | --- |
| **bench (client 视角)** | `vllm bench serve` | `qwen05b-random-30.json` + 终端 summary | 每个请求的真实 TTFT / TPOT / ITL + percentile + 端到端 throughput | 30 req / 10.47s / 2.87 req/s / **TTFT median 123.5ms / p99 149ms** / TPOT median 38.3ms / out 91.7 tok/s |
| **engine (server counters)** | `profile --kind engine` | `NNNN-HHMMSS.prom` + `summary.txt` | vllm 内部累计 counters（已用 token / KV / batch 大小 / finish reason） | 8 traffic req: `prompt_tokens_total` 1847→2239 (+392), `success_length` 21→29 (+8) |
| **torch (Python + torch op)** | `profile --kind torch` | `*.pt.trace.json.gz` + `rank*_ascend_pt/` | python 调用栈 + torch op 时间 + NPU kernel launch timeline（chrome://tracing） | 3 req: 1 个 1.5MB trace json.gz |
| **msprof (NPU kernel 级)** | `profile --kind msprof` | `PROF_*/mindstudio_profiler_output/*.csv` + `msprof_*.json` | aic metrics (ArithmeticUtilization / PipeUtilization / Memory / L2Cache) + 逐 kernel 时间 | 12s / 2 req: `op_summary.csv` 13MB / `msprof.json` 126MB |

### "bench 的 profile 过程" 推荐用法

最常用组合：**bench 制造负载 + engine profile 抓 server counters**：

```bash
# 终端 1：profile 持续抓 metrics（duration 要 > bench 跑完时间）
VLLM_HUST_API_KEY=testkey123 \
  bash scripts/manage-container.sh profile --kind engine \
    --label bench-combo --duration 80 --interval 2

# 终端 2：跑 bench（30 req 约 10s）
source /root/miniconda3/etc/profile.d/conda.sh
conda activate vllm-hust-dev
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p /tmp/vllm-hust-manager/bench
vllm bench serve \
  --backend vllm --model qwen2.5-0.5b --served-model-name qwen2.5-0.5b \
  --tokenizer /root/.cache/huggingface/hub/Qwen2.5-0.5B-Instruct \
  --tokenizer-mode auto --host 127.0.0.1 --port 8001 \
  --header "Authorization=Bearer testkey123" \
  --dataset-name random --random-input-len 128 --random-output-len 32 \
  --num-prompts 30 --max-concurrency 4 --request-rate inf \
  --save-result --result-dir /tmp/vllm-hust-manager/bench \
  --result-filename qwen05b-random-30.json --label qwen2.5-0.5b-random-npu1 \
  --ready-check-timeout-sec 30 --seed 0
```

产物：

- `profile/engine/bench-combo-<ts>/*.prom` —— 负载前后的 server counters
- `bench/qwen05b-random-30.json` —— 端到端 percentile latency + throughput

读法（bench.json）：

| 字段 | 含义 | 期望区间（Qwen2.5-0.5B eager, max-num-seqs=8）|
| --- | --- | --- |
| `mean_ttft_ms` / `p99_ttft_ms` | prompt 提交到第一个 token 出来 | < 200ms（短 prompt）|
| `mean_tpot_ms` / `p99_tpot_ms` | 每 token decode 延迟（不含 1st）| 30-50ms（0.5B 短 batch）|
| `mean_itl_ms` | inter-token latency | 跟 TPOT 接近（无流式 chunking）|
| `output_throughput` (tok/s) | generation 端总吞吐 | 80-200 tok/s (0.5B 1卡)|
| `total_token_throughput` (tok/s) | prompt+gen 加权 | 400-500 tok/s（prompt 占大头）|
| `request_throughput` (req/s) | 请求级吞吐 | concurrency / mean_latency |
| `max_concurrent_requests` | 实际峰值并发 | 4 (这次设的 max_concurrency=4)|
| `rtfx` | required-to-first-x, e2e/输出 tok | 0 = vllm bench 暂未实现 |

### 把 profile 数据"读"成结论

一次完整 profile 跑出来的产物，按下列顺序看：

1. **`summary.txt` 关键指标 + `traffic.log` / bench.json** —— 一眼看吞吐 / 延迟是否合理
2. **`*.prom` 间隔对比** —— 把 idle 快照 vs 加载中快照 vs final 快照的 diff 拿出来：
   - `prompt_tokens_total` 差值 = 真实处理的 prompt tok 数（验证请求真到 engine）
   - `generation_tokens_total` 差值 = 真实生成的 tok 数
   - `request_success_total{finished_reason="length"}` 增长 = 截断（max_tokens 不够）
   - `request_success_total{finished_reason="error"}` 增长 = 出错（看 engine.log）
3. **`*.pt.trace.json.gz`（torch）** —— chrome://tracing 打开，看 python 主线程 / torch op / NPU kernel 三段时间，看是不是有"空档"（idle gap）
4. **`PROF_*/op_summary.csv`（msprof）** —— 按 `Type` 排序，看哪些 kernel 占时间最多：
   - `CONV` / `Matmul` / `FlashAttentionScore` —— 计算密集
   - `Malloc` / `Memcpy` / `DataTransfer` —— 数据搬运开销
   - 通过 `PipeUtilization` 看出 aic pipeline 利用率
5. **跨工具交叉验证**：
   - bench 报的 `mean_ttft_ms` ≈ torch trace 里 `1st-token` 之前的 python+launch 时间
   - bench 报的 `mean_tpot_ms` ≈ msprof 里 decode 阶段 kernel 时间 / 1
   - engine `generation_tokens_total` 差值 / bench duration ≈ engine 视角的 output tok/s，应该和 bench 报的数字一致（误差 < 5%）

## 已知陷阱

1. **NPU 0 内存被占**：之前 P1 调试时杀掉的 EngineCore 进程可能没完全释放 NPU HBM。`npu-smi info`
   看 `Memory-Usage(MB)`，如果某个 NPU 显示 > 50 GB 但没有相关 PID，需要切到空闲 NPU（2-7）或者重启
   容器。`profiles/inplace-qwen2.5-0.5b-npu1.env` 默认 NPU 0，遇到这种情况请用 `--config VLLM_ENGINE_NPU_DEVICES=<其他>`。

2. **改 `DEFAULT_PORT` 不生效**：profile 文件（如 `profiles/inplace-qwen2.5-0.5b-npu1.env`）里
   显式写了 `VLLM_ENGINE_PORT=8000`，会覆盖脚本内 `DEFAULT_PORT`。**改端口必须改 profile 里的
   `VLLM_ENGINE_PORT`**，或用 `--config VLLM_ENGINE_PORT=<n>` 一次性覆盖。配置优先级：
   CLI > state.env > **profile** > env > 内置默认。

3. **8000 端口被 orphan 占用**：其他用户 / 之前会话残留的 uvicorn / vllm 进程可能占着 8000，
   让 health 检查假阳性（见上面 curl 问题）。`manage-container.sh` 的 `cmd_start` 会先 pkill
   `VLLM::EngineCore`，但要彻底干净请用别的 port：
   `--config VLLM_ENGINE_PORT=<free-port>`。当 `/proc/net/tcp` 看到 LISTEN 但 `ps` 找不到 owner
   时，是 kernel 持有的 orphan socket（msprof / EngineCore 强杀后未释放），只能换 port 或重启驱动。

4. **state.env 缺失时的 false-positive**：如果 `state.env` 丢了，`status` / `health` 会 fallback 到
   默认 `PORT=8000`，如果此时有 orphan uvicorn 占着 8000，会报 `health=healthy` 而 `state=stopped` —
   这是有意的诊断信号，不是 bug。

5. **msprof --aic-metrics 是单值**：msprof CLI 不接受 `,` 分隔串，必须重复传多个 flag。脚本在
   `build_msprof_command` 里把 `|` / `,` 分隔的输入展开为多个 `--aic-metrics=X`。

6. **msprof 强杀后导出**：msprof `--duration` 到点不保证 100% 优雅退出；脚本在 `kill -TERM` 后
   多等 5s 再 `pkill -9 -f "VLLM::EngineCore"`，避免 EngineCore 占 NPU 内存导致下次 start 失败。

7. **`require_api_key` 必须用 `if/else` 不能用 `&&` 短路**：`set -e` 模式下，
   `[[ A || B ]] && { ... }` 整体返回 1 时，**function** 返回 1 仍会触发外层 `set -e` 退出（虽然
   shell 文档说 `&&` 列表是例外）。所以 `require_api_key` 用 `if [[ ... ]]; then exit 1; fi` 形式，
   测试 `unset VLLM_HUST_API_KEY && bash manage-container.sh status` 应该通过。

8. **`--profiler-config` 启动的 vllm 对 NPU 内存更敏感**：带 profiler 启动的 engine 似乎在 NPU 0
   HBM 已被其他 session 占满时直接 ValueError（不是 out-of-memory，而是"free memory < GPU
   memory utilization target"）。如果 NPU 0 不可用，先 `npu-smi info` 找空闲卡，再用
   `--config VLLM_ENGINE_NPU_DEVICES=<n> --config ASCEND_RT_VISIBLE_DEVICES=<n>` 切过去。

9. **profile_torch 测完会自动恢复原 engine（用 cfg_bak 保留当时 NPU/port/mem_util）**：
   `profile_torch` 测完默认会调 `cmd_start` 恢复"原 engine"。但 **CLI `--config` 覆盖不写进
   `state.env`**（避免 secret 污染 + 保留动态性），所以脚本额外维护一份 `state.env.torch-cfg-bak`，
   把当时生效的关键 env（`VLLM_ENGINE_NPU_DEVICES` / `ASCEND_*` / port / mem_util / TP / max-num-seqs）
   备份到 `cfg_bak` + 归档一份到 out_dir 的 `cfg.env`。step 10 用 `set -a; source cfg_bak; cmd_start`
   注入 cfg，让 `cmd_start` 用**测时**的 NPU/port 启动，而不是 fallback 到 profile 默认值。
   - 想测完不自动恢复：传 `--keep-engine-running`（设 `VLLM_PROFILE_TORCH_KEEP=1`）
   - 想看测时 env：打开 `<out_dir>/cfg.env`
