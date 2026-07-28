# 参数与输出参考

spec JSON 里有三层输入(`server_parameters` / `client_parameters` / `export`),产出 `run_leaderboard.json` 里有两层输出(`metrics` / `constraints.metrics`)。一句话区分:`server_parameters` 控制服务怎么起,`client_parameters` 控制客户端怎么打,`export` 控制归档到 leaderboard 时挂什么标签;`metrics` 是客户端实测值,`constraints.metrics` 是业务约束类相对指标。

## 输入三层结构

| 层级 | 字段 | 含义 | 必填 | 典型值 |
|------|------|------|------|--------|
| server_parameters | tensor_parallel_size | TP 大小,910B2 单卡为 1 | 必填 | 1 |
| server_parameters | gpu_memory_utilization | NPU 显存占用比例,official baseline 固定 0.6 | 必填 | 0.6 |
| server_parameters | enforce_eager | 是否强制 eager;空=图模式,`"1"`=强制 eager | 可选 | `""` |
| server_parameters | trust_remote_code | 是否启用 trust_remote_code;空=不启用,`"1"`=启用 | 可选 | `""` |
| server_parameters | disable_log_stats | 是否关闭 stats 日志;空=启用,`"1"`=关闭 | 可选 | `""` |
| server_parameters | disable_log_requests | 是否关闭请求日志;空=启用,`"1"`=关闭 | 可选 | `""` |
| server_parameters | host | 服务监听地址(serve 场景) | 必填(serve) | `0.0.0.0` |
| server_parameters | port | 服务监听端口(serve 场景) | 必填(serve) | `8000` |
| server_parameters | max_model_len | 最大上下文长度 | 必填 | `32768` |
| client_parameters | backend | 后端类型,决定 endpoint;`vllm`→`/v1/completions`,`openai-chat`→`/v1/chat/completions` | 必填 | `vllm` |
| client_parameters | endpoint | HTTP 路径,与 backend 配套 | 必填 | `/v1/completions` |
| client_parameters | dataset_name | 数据集类型 | 必填 | `random` |
| client_parameters | dataset_path | 数据集文件路径;ShareGPT/sonnet/hf 用 | 可选 | `ShareGPT_V3_unfiltered_cleaned_split.json` |
| client_parameters | no_stream | 是否禁用流式;`false`=启用流式 | 可选 | `false` |
| client_parameters | num_prompts | 本次请求条数 | 必填 | `200` |
| client_parameters | input_len | 合成数据输入 token 长度(仅 random/prefix_repetition) | 可选 | `1024` |
| client_parameters | output_len | 合成数据输出 token 长度(仅 random/prefix_repetition) | 可选 | `256` |
| client_parameters | request_rate | 请求发送速率(req/s);`1`=串行(serve 场景) | 必填(serve) | `1` |
| client_parameters | host | 客户端连接目标地址 | 必填(serve) | `127.0.0.1` |
| client_parameters | port | 客户端连接目标端口 | 必填(serve) | `8000` |
| client_parameters | batch_size | 批大小(仅 throughput/latency) | 可选 | `8` |
| client_parameters | num_iters_warmup | 预热迭代数(仅 latency) | 可选 | `10` |
| client_parameters | num_iters | 正式迭代数(仅 latency) | 可选 | `30` |
| client_parameters | num_warmups | 预热次数(仅 throughput) | 可选 | `0` |
| client_parameters | gpu_memory_utilization | NPU 显存占用比例(throughput/latency 离线模式,无 server 时放这里) | 可选 | `0.6` |
| export | engine | artifact 里 `engine` 字段 | 必填 | `vllm` |
| export | engine_version | engine 版本 | 必填 | `0.18.0` |
| export | submitter | 提交者标识 | 必填 | `official-ascend-baseline` |
| export | baseline_engine | 对照 baseline engine 名 | 可选 | `vllm` |
| export | github_repository | provenance 仓库 | 必填 | `vllm-project/vllm-ascend` |
| export | github_ref | provenance ref | 必填 | `v0.18.0` |
| export | git_commit | provenance commit | 可选 | `e18643f8a4d5bd9990727654318ad069ea0b56e2` |
| export | data_source | 数据来源标签 | 必填 | `reference-vllm-ascend-benchmark` |

## 输出两层结构

### metrics(raw 实测值)

| 字段 | 含义 | 单位 | 0/null 含义 |
|------|------|------|-------------|
| ttft_ms | Time To First Token,首 token 延迟 | ms | 未采集 |
| tbt_ms | Time Between Tokens(TPOT),token 间延迟 | ms | 未采集 |
| throughput_tps | 输出 token 吞吐 | tokens/s | 未采集 |
| peak_mem_mb | 峰值显存 | MB | `0`=本次未采集 |
| error_rate | 请求错误率 | 比例 | `0.0`=全部成功 |

### constraints.metrics(业务约束指标,共 16 个,顺序固定)

| 字段 | 含义 | 类型 | null 的含义 |
|------|------|------|-------------|
| single_chip_effective_utilization_pct | 单卡有效利用率 | number/null | 未采集或不可从 raw benchmark 自动推导 |
| typical_throughput_ratio_vs_baseline | 相对 baseline 吞吐比值 | number/null | 未采集或不可从 raw benchmark 自动推导 |
| typical_ttft_reduction_pct_vs_baseline | 相对 baseline TTFT 降低 % | number/null | 未采集或不可从 raw benchmark 自动推导 |
| typical_tpot_reduction_pct_vs_baseline | 相对 baseline TPOT 降低 % | number/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_length | 长上下文长度,通常等于 max_model_len | number/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_throughput_stable | 长上下文吞吐是否稳定 | bool/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_ttft_p95_ms | 长上下文 TTFT p95 | number/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_ttft_p99_ms | 长上下文 TTFT p99 | number/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_tpot_p95_ms | 长上下文 TPOT p95 | number/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_tpot_p99_ms | 长上下文 TPOT p99 | number/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_ttft_p95_stable | TTFT p95 是否稳定 | bool/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_ttft_p99_stable | TTFT p99 是否稳定 | bool/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_tpot_p95_stable | TPOT p95 是否稳定 | bool/null | 未采集或不可从 raw benchmark 自动推导 |
| long_context_tpot_p99_stable | TPOT p99 是否稳定 | bool/null | 未采集或不可从 raw benchmark 自动推导 |
| unit_token_cost_reduction_pct | 单位 token 成本降低 % | number/null | 未采集或不可从 raw benchmark 自动推导 |
| multi_tenant_high_utilization | 多租户高利用率 | bool/null | 未采集或不可从 raw benchmark 自动推导 |

`null` 字段需手工在 `constraints_metrics` 文件里补,或留空表示"暂无数据"。stub 模板见 `docs/official-baselines/official-ascend-constraints.stub.json`,所有字段默认 `null`。

## 4 个 scenario 参数差异对比

均为 910B2 单卡 Qwen2.5-14B-Instruct,server_parameters 一致(TP=1, gpu_memory_utilization=0.6, max_model_len=32768)。throughput/latency 离线模式不启服务,`gpu_memory_utilization` 放在 client_parameters 里。

| 维度 | random-online | sharegpt-online | sonnet-throughput | random-latency |
|------|---------------|-----------------|-------------------|----------------|
| benchmark_type | serve | serve | throughput | latency |
| 是否启服务 | 是 | 是 | 否 | 否 |
| dataset_name | random | sharegpt | sonnet | random |
| dataset_path | - | `ShareGPT_V3_unfiltered_cleaned_split.json` | `benchmarks/sonnet.txt` | - |
| num_prompts | 200 | 200 | 200 | - |
| input_len | 1024 | - | - | 1024 |
| output_len | 256 | - | - | 128 |
| request_rate | 1 | 1 | - | - |
| batch_size | - | - | - | 8 |
| num_iters_warmup | - | - | - | 10 |
| num_iters | - | - | - | 30 |
| 典型用途 | 合成在线服务冒烟与回归 | 真实对话流量在线服务 | 离线吞吐(无在线压力) | 单 batch 延迟 SLO |

## spec_id 命名规则

格式:`official-ascend-jan-2026-v0180-<scenario>-<model_short>-<chip_count_expr>-<chip_model>.json`

单卡文件默认 chip_count=1,文件名不带 chip 段;多卡变体文件名带 `2chip` / `4chip` / `8chip`。

示例解析 `official-ascend-jan-2026-v0180-random-online-qwen25-14b-910b2.json`:

| 段 | 值 | 含义 |
|----|----|------|
| 系列 | `official-ascend-jan-2026-v0180` | baseline 系列,2026 年 1 月,v0.18.0 |
| scenario | `random-online` | 场景名 |
| model_short | `qwen25-14b` | 模型短名(Qwen2.5-14B-Instruct) |
| chip_model | `910b2` | 芯片型号 |

多卡示例:`official-ascend-jan-2026-v0180-sonnet-throughput-qwen25-14b-4chip-910b2.json`(4 卡)。

另有一套 `perfgate-ascend-<scenario>-qwen25-3b-910b2.json`,是 perfgate 用的小模型快速门槛 spec,与 official baseline 不是一回事。
