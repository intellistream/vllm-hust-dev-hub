# Sage Mate Mod compatibility candidate status (2026-09-04)

The exact target is Core `762f85b3` / `0.28.1rc1.dev319`, Ascend `4e57439e` /
`0.25.1rc1`, Qwen3.8-27B, Ascend TP4, graph mode. Legacy images, TP1 and eager
mode are not accepted as final qualification paths.

## Current status

| Mod | Source state | Runtime state | Compatibility verdict |
| --- | --- | --- | --- |
| BidKV | migrated to versioned preemption-policy API v1; no runtime monkey patch | Qwen3.8-27B TP4 graph: four long concurrent requests completed; 187 policy calls, 0 failures; output, cancellation/recovery and rollback passed | compatible for the exact tested lane |
| DiffSpec | current Eagle3, hybrid-attention, runner and metadata source surfaces adapted | blocked: local Qwen3-1.7B draft vocab `151936` does not match target vocab `248320`; no validated Qwen3.8 Eagle3 draft is available | blocked / not qualified |
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
used NPU0-3 for the TP4 runs. Native Engine reserved NPU4-7 remained excluded and its
PIDs did not change. Every launch used the managed service path; no TP1, eager or
legacy-image result was accepted. The original Qwen3.8-27B TP4 graph service was
restored, returned HTTP 200 and produced `LATCHMOE_ROLLBACK_OK`.

## Measured results

- BidKV pressure run: 4 × (12,517 input + 2,048 requested output tokens), all HTTP
  200, wall time 336.584 s, policy calls 187, failures 0, utility selections 6,
  liveness fallbacks 181.
- LatchMoE Qwen3-30B-A3B: 10-request TTFT p50/p95 3.678/7.730 s,
  latency p50/p95 25.941/31.808 s, output throughput p50/p95 2.907/3.010 tok/s.
  The no-plugin baseline output throughput was about 23.57 tok/s.
- DiffSpec: 38 source tests passed, but the draft checkpoint gate stopped device
  qualification. No acceptance-rate or latency number is reported.

## Candidate commits and publication gate

Machine-readable candidates are in
[`config/sage-mate-mod-candidate-lock.json`](../config/sage-mate-mod-candidate-lock.json).
They are tested local feature-branch commits, not yet public installable locks. Core contribution
instructions require a human to review every proposed line, run the required tests and
make the required AI-use disclosure before an upstream PR is opened. The proposed
preemption-policy API must also be coordinated with upstream RFC #51608 and draft PRs
#51601/#53723 instead of opening a duplicate. Ascend changes now have real NPU
evidence but still require signed-off commits from a fork and human review.
Consequently no official upstream PR URL or main-branch publication is claimed yet.
