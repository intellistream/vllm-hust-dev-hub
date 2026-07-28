# 项目结构总览

`vllm-hust-dev-hub` workspace 是一个多仓协作、单链路收口的项目:17 个 folder 按 Hub/引擎/编排/Web 等角色分工,benchmark 运行时语义统一收口在引擎层,编排与导出收口在 benchmark 层,前端只消费不写逻辑。

最小责任链:

```
vllm-hust(运行时) → vllm-hust-benchmark(编排导出) → vllm-hust-website(前端消费) → reference-repos(只读对照)
```

## 仓库角色分组表

| 分组 | 仓库名 | workspace 显示名 | 角色 | 一句话功能 | Source-of-Truth 边界 |
|---|---|---|---|---|---|
| Hub | vllm-hust-dev-hub | dev-hub | 编排中枢 | workspace 入口、bootstrap 脚本、Ascend 容器助手、`manage.sh` 引擎服务管理 | 工作流编排与 host-managed 引擎服务启动路径 |
| 文档与组织 | vllm-hust-docs | docs | 文档仓 | 跨仓共享文档与站点内容 | 跨仓共享文档来源 |
| 文档与组织 | vllm-hust-org-profile | org-profile | 组织资料 | 组织 profile、code-of-conduct、贡献者名录等 | 组织级元数据 |
| 引擎 | vllm-hust | [engine] vllm-hust | 运行时 | vLLM 的 HUST fork,提供 `vllm bench serve/throughput/latency/sweep` 命令与上游 performance suite | benchmark 运行时语义 |
| 引擎 | vllm-ascend-hust | [engine] vllm-ascend-hust | Ascend 后端 | vLLM-Ascend 的 HUST fork,提供 Ascend NPU 后端插件 | Ascend 平台适配 |
| 引擎 | vllm-ascend-quant-hust | [engine] vllm-ascend-quant-hust | 量化插件 | Ascend 量化插件(W8A8 等) | Ascend 量化算子 |
| 引擎 | triton-ascend-hust | [engine] triton-ascend-hust | Triton 后端 | Triton Ascend 后端 | Triton-on-Ascend 编译路径 |
| 引擎 | ascend-runtime-manager | [engine] ascend-runtime-manager | 环境管理 | host-level Ascend 环境管理工具(`hust-ascend-manager`) | CANN/torch_npu 安装与 host 容器编排 |
| Benchmark 编排 | vllm-hust-benchmark | [perf] benchmark | 编排中枢 | 场景注册、命令拼装、结果导出、submission 归档、snapshot 生成、HF 同步、official baseline 自动化 | leaderboard 场景定义与 submission contract |
| Benchmark 编排 | vllm-hust-perf-analyzer | [perf] perf-analyzer | 性能分析 | 性能分析器,msprof/TraceLoom 等的下游消费者 | 下游消费 profiling 产物 |
| 服务与 Web | vllm-hust-workstation | [web] workstation | Web 工作站 | 面向成员的内部工具 | — |
| 服务与 Web | vllm-hust-website | [web] website | 官网前端 | 公开官网与 leaderboard 前端 | 公开 leaderboard 数据消费,不写运行时逻辑 |
| 工具与研究 | claude-code-hust | [tool] claude-code-hust | 工具 | Claude Code 的 HUST 扩展工具 | — |
| 工具与研究 | EvoScientist | [research] EvoScientist | 研究系统 | 多智能体研究系统,其 trace 是 benchmark workload 之一(`agent-research-online` 场景) | `agent-research-online` 场景 workload 来源 |
| 论文 | cccf-domestic-inference-engine-survey | [paper] cccf-inference-survey | 论文 | CCCF 国产推理引擎综述 | — |
| 论文 | fcs-domestic-chip-llm-recsys | [paper] fcs-llm-recsys | 论文 | FCS 国产芯片 LLM 推荐系统论文 | — |
| Reference | reference-repos | [ref] reference-repos | 只读对照 | 上游只读对照克隆,含 `reference-repos/vllm`、`reference-repos/vllm-ascend`、`reference-repos/sglang` | pinned baseline worktree,严禁开发 |

## 关键责任边界

- benchmark 运行时语义归 `vllm-hust`,`vllm-hust-benchmark` 不重写引擎的 runtime benchmark 逻辑。
- leaderboard 场景定义与 submission contract 归 `vllm-hust-benchmark`。
- 公开 leaderboard snapshot 消费归 `vllm-hust-website`,website 不手工维护 snapshot。
- 官方 baseline 必须跑 `reference-repos/vllm` + `reference-repos/vllm-ascend` 的 pinned worktree(`v0.18.0` 这对),不能在 reference-repos 里写代码。
- host-managed 引擎服务启动路径归 `dev-hub/manage.sh`,不要绕开它手工起 vllm。

## 打开 workspace 后该看哪里

- 想了解 dev-hub 仓本身:看 `vllm-hust-dev-hub/README.md`
- 想跑/管理引擎服务:看 `vllm-hust-dev-hub/manage.sh` 与 `scripts/run_vllm_hust_engine.sh`
- 想跑 benchmark 或建 baseline:看 `vllm-hust-benchmark/README.md` 与 `docs/benchmark-guides/02-benchmark-paths.md`
- 想看参数与输出含义:看 `docs/benchmark-guides/03-params-outputs-reference.md`
- 想看官网 leaderboard:看 `vllm-hust-website/README.md`
