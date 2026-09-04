# Sage Mate Mod compatibility candidate status (2026-09-04)

The exact target is Core `762f85b3` / `0.28.1rc1.dev319`, Ascend `4e57439e` /
`0.25.1rc1`, Qwen3.8-27B, Ascend TP4, graph mode. Legacy images, TP1 and eager
mode are not accepted as final qualification paths.

## Current status

| Mod | Source state | Runtime state | Compatibility verdict |
| --- | --- | --- | --- |
| BidKV | migrated to versioned preemption-policy API v1; no runtime monkey patch | independent TP4 graph run pending | unknown / not qualified |
| DiffSpec | current Eagle3, hybrid-attention, runner and metadata source surfaces adapted | blocked: local Qwen3-1.7B draft vocab `151936` does not match target vocab `248320`; no validated Qwen3.8 Eagle3 draft is available | blocked / not qualified |
| LatchMoE | latest Ascend dataclass and MoE seam-v2 source surfaces adapted | Qwen3.8-27B is dense and therefore not applicable; separate Qwen3-30B-A3B TP4 graph run pending | N/A for Qwen3.8; unknown for MoE lane |

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

No hardware command or service mutation was run during this adaptation. Production
NPU0-3 and Native Engine reserved NPU4-7 are explicitly excluded. No independent TP4
allocation is currently registered, so hardware qualification is pending rather than
silently redirected to a legacy, TP1 or eager lane.

## Candidate commits and publication gate

Machine-readable candidates are in
[`config/sage-mate-mod-candidate-lock.json`](../config/sage-mate-mod-candidate-lock.json).
They are local feature-branch commits, not public installable locks. Core contribution
instructions require a human to review every proposed line, run the required tests and
make the required AI-use disclosure before an upstream PR is opened. The proposed
preemption-policy API must also be coordinated with upstream RFC #51608 and draft PRs
#51601/#53723 instead of opening a duplicate. Ascend changes likewise require real NPU
tests and signed-off commits from a fork. Consequently no official upstream PR URL or
main-branch publication is claimed yet.
