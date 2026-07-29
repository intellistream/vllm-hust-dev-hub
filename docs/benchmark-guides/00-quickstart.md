# 00 - 快速上手

## 适用读者与场景

| 项 | 说明 |
|----|------|
| 读者 | 刚加入团队、需要在 910B2 NPU 机器上跑第一条 benchmark 的成员 |
| 机器 | 已有 910B2 NPU 机器的 root/普通用户权限 |
| 依赖 | 已安装 conda/miniconda |

## 一次性环境准备

### 1. clone workspace 仓

```bash
# 选一个工作目录
export WORKSPACE_ROOT=<你的工作目录,如 /home/<user>/vllm-hust-workspace>
mkdir -p $WORKSPACE_ROOT && cd $WORKSPACE_ROOT

# clone dev-hub(它自带 workspace clone 脚本)
git clone https://github.com/vLLM-HUST/vllm-hust-dev-hub.git
cd vllm-hust-dev-hub

# 用 dev-hub 的脚本 clone 其他 sibling 仓
bash scripts/clone-workspace-repos.sh
```

clone 完成后目录结构:

```
$WORKSPACE_ROOT/
├── vllm-hust-dev-hub/      # 本仓,workspace 入口
├── vllm-hust/              # vllm-hust fork(路径 A/C/E 的源码)
├── vllm-ascend-hust/       # ascend 插件 fork
└── vllm-hust-benchmark/    # benchmark 主入口(脚本与 spec 都在这里)
```

### 2. 创建 conda env

```bash
# 路径 A/C/E 用的 env
conda create -n vllm-hust-dev python=3.11 -y
conda activate vllm-hust-dev

# 在 vllm-hust 仓内安装(editable)
cd $WORKSPACE_ROOT/vllm-hust
pip install -e .

# 在 vllm-hust-benchmark 仓内安装(editable)
cd $WORKSPACE_ROOT/vllm-hust-benchmark
pip install -e .
```

### 3. 验证 NPU

```bash
npu-smi info
# 应看到 910B2 设备,Chip Name 含 910B2
```

### 4. 设置环境变量

```bash
# 加到 ~/.bashrc 或 ~/.zshrc
export WORKSPACE_ROOT=<你的工作目录>
export CURRENT_ENV_PREFIX=$CONDA_PREFIX
export CURRENT_VLLM_HUST_REPO=$WORKSPACE_ROOT/vllm-hust
export CURRENT_VLLM_ASCEND_HUST_REPO=$WORKSPACE_ROOT/vllm-ascend-hust
export HF_ENDPOINT=https://hf-mirror.com
```

## 5 分钟跑通路径 A 冒烟

路径 A 冒烟是路径 A 的一个案例(同一路径,不同使用场景),用 manage.sh 启小模型 + 少量 prompt 快速验证环境。

```bash
cd $WORKSPACE_ROOT/vllm-hust-dev-hub

# 1. 配置 API key
cp .env.template .env
# 编辑 .env,填入 VLLM_HUST_API_KEY=<任意字符串,本地用 dummy 即可>

# 2. 启服务(用 7B 小模型 + 单卡)
VLLM_ENGINE_ENV_FILE=profiles/smoke-qwen2.5-7b-npu1.env bash manage.sh start

# 3. 等服务就绪(看到 "Application startup complete")
# 4. 跑一个小 benchmark(smoke profile 默认端口 18166)
conda activate vllm-hust-dev
cd $WORKSPACE_ROOT/vllm-hust
vllm bench serve \
  --model Qwen/Qwen2.5-7B-Instruct \
  --endpoint http://localhost:18166/v1 \
  --num-prompts 10 \
  --dataset-name random
```

## 看懂输出的 3 个关键字段

跑完后输出会包含类似:

```
Successful requests: 10
Total throughput: 245.12 tokens/s
Mean TTFT: 132.45 ms
Mean TPOT: 34.21 ms
```

记下这 3 个数,含义见 [10-output-metrics-guide.md](10-output-metrics-guide.md):

| 字段 | 含义 | 判定 |
|------|------|------|
| `TTFT`(首 token 延迟) | 从请求到收到第一个 token 的时间 | < 300ms 正常,> 500ms 算回归 |
| `throughput`(吞吐) | 单位时间产出 token 数 | 越高越好 |
| `error_rate`(错误率) | 失败请求占比 | 必须为 0 |

## 常见 3 个错误及排查

| 错误 | 原因 | 排查命令 |
|------|------|---------|
| `ModuleNotFoundError: vllm` | conda env 未激活或 vllm 未装 | `which python` 应指向 `vllm-hust-dev` env;`pip show vllm` 应有输出 |
| `FileNotFoundError: model` | 模型路径不对或未下载 | `ls $CURRENT_MODEL_PATH` 应存在;首次需 `huggingface-cli download Qwen/Qwen2.5-7B-Instruct` |
| `Address already in use :8001` | 端口被占 | `lsof -i:8001` 找占用进程;`bash manage.sh stop` 停旧服务 |

## 下一步导航

| 你想做什么 | 去哪篇 |
|-----------|--------|
| 选一条正式 benchmark 路径跑 | [02-benchmark-paths.md](02-benchmark-paths.md) |
| 查某个脚本的参数 | [07-params-cheatsheet.md](07-params-cheatsheet.md) |
| 做 backfill 补数据 | [04-backfill-paths.md](04-backfill-paths.md) |
| 看懂 benchmark output 每个字段 | [10-output-metrics-guide.md](10-output-metrics-guide.md) |
| 调查性能回归 | [08-regression-bisect-sop.md](08-regression-bisect-sop.md) |
| 多卡或 KV cache 研究 | [09-multi-chip-and-research.md](09-multi-chip-and-research.md) |
| 了解项目结构与各仓职责 | [01-project-overview.md](01-project-overview.md) |
