# Sage Mate Mod compatibility candidate status (2026-09-04)

The exact target is Core `762f85b3` / `0.28.1rc1.dev319`, Ascend `4e57439e` /
`0.25.1rc1`, Qwen3.8-27B, Ascend TP4, graph mode. Legacy images, TP1 and eager
mode are not accepted as final qualification paths.

## Current status

| Mod | Source state | Runtime state | Compatibility verdict |
| --- | --- | --- | --- |
| BidKV | migrated to versioned preemption-policy API v1; no runtime monkey patch | Qwen3.8-27B TP4 graph: four long concurrent requests completed; 187 policy calls, 0 failures; output, cancellation/recovery and rollback passed | compatible for the exact tested lane |
| DiffSpec | current Eagle3, Ascend attention, model runner, sampler and speculative metadata surfaces adapted | Qwen3.8-27B plus `VirVen/Qwen3.5-27B-EAGLE3-v2` passed TP4 FULL_DECODE_ONLY graph, four-rank draft loading, output, cancellation/recovery, concurrency and long-context gates | functional-compatible, but performance degraded (acceptance 19.29%; ~14.00 vs ~47.72 tok/s target-only P50) |
| LatchMoE | current MoE routing quantization and MLP-builder ABI adapted through seam v2 | Qwen3.8-27B is dense and Not Applicable; Qwen3-30B-A3B passed TP4 PIECEWISE graph, four-rank mapping, swap, 48/48 address checks, concurrency, cancellation and exception recovery | functional-compatible for Qwen3-30B-A3B, but performance degraded (~2.91 vs ~23.57 tok/s baseline) |

The target model config identifies `Qwen3_5ForConditionalGeneration` with a
hybrid GDN/full-attention text stack. Marketing/model-path naming must not override
the architecture and vocabulary recorded by the actual config.

## Lifecycle and evidence rule

`installed`, `configured`, `enabled`, and `runtimeEffective` are separate states.
Only the last state means the live worker and bounded inference request observed the
candidate. Exact version or source matching, successful installation, Manager
admission, unit tests and graph configuration are necessary but cannot set
`compatible` without real execution evidence.

A qualifying run must retain exact source/image/model provenance, all four rank logs,
graph capture/replay evidence, bounded output comparisons, failure injection and
rollback/recovery records, and metrics. BidKV additionally needs policy call/selection/
failure counters. DiffSpec needs per-rank draft and accept/reject/KV metadata witnesses,
concurrent cancellation/recovery, acceptance rate, P50/P95 latency and throughput.
LatchMoE needs per-rank expert mapping, host/device swap witnesses and stable graph
addresses on its separate MoE model.

## Resource gate

After explicit authorization, the campaign stopped the managed Sage Mate service and
used NPU0-3 for the TP4 runs. Native Engine reserved NPU4-7 remained excluded; the
campaign did not start, stop or configure its independently managed workload. Every launch used the managed service path; no TP1, eager or
legacy-image result was accepted. The original Qwen3.8-27B TP4 graph service was
restored after each Mod, returned HTTP 200 and finally produced `DIFFSPEC_ROLLBACK_OK`.

## Measured results

- BidKV pressure run: 4 × (12,517 input + 2,048 requested output tokens), all HTTP
  200, wall time 336.584 s, policy calls 187, failures 0, utility selections 6,
  liveness fallbacks 181.
- LatchMoE Qwen3-30B-A3B: 10-request TTFT p50/p95 3.678/7.730 s,
  latency p50/p95 25.941/31.808 s, output throughput p50/p95 2.907/3.010 tok/s.
  The no-plugin baseline output throughput was about 23.57 tok/s.
- DiffSpec: final contract suite 26/26. Four ranks loaded the qualified draft and
  entered ACLGraph; 4/4 graph captures completed. Two 10-request suites were
  correct, four concurrent answers were correct, cancellation drained in 0.529 s,
  malformed-request recovery and a 5,425-token prompt passed. Draft/accepted
  counters were 534/103 (19.29%). Warm TTFT P50/P95 was 0.459/0.469 s, latency
  P50/P95 0.744/3.990 s, and output throughput P50/P95 14.00/14.24 tok/s versus
  target-only 47.72/56.97 tok/s; therefore the lane is not an acceleration recommendation.

## Candidate commits and publication gate

Machine-readable candidates are in
[`config/sage-mate-mod-candidate-lock.json`](../config/sage-mate-mod-candidate-lock.json).
The qualified commits have been pushed to the `vLLM-HUST` organization `main`
branches. The rebased Core organization-main commit is `a4d6aa022f`; the exact
tested baseline artifact remains `7362232895` and is retained separately in the
lock. No submission to `vllm-project` or `vllm-project/vllm-ascend` was requested
or made; their RFCs and PRs are duplicate-work context, not publication gates for
the organization repositories.

On 2026-09-05 the accidentally transferred BidKV repository was transferred
back intact from `Qixin-Gaoke` to `vLLM-HUST`. Its canonical repository is now
`https://github.com/vLLM-HUST/vllm-hust-bidkv`, and organization `main` resolves
to documentation head `5fb109be683f486dfdf45d50f88c6138e003637e` with the
qualified runtime commit `463f798b209a33ff2d2f4e277b9aedb26d75fa29` in history.
