---
description: "Use when working on vllm-hust fork changes, domestic hardware enablement, AGI4S serving optimizations, backend or registry extensions, multimodal or structured-output paths, reasoning or tool-calling support, or upstream-merge-safe refactors."
name: "vllm-hust Localization Guidance"
---

# vllm-hust Localization Guidance

- Treat this repository as an upstream-compatible fork of vLLM. The default goal is to preserve mergeability with upstream while landing localized optimizations for domestic hardware and AGI4S workloads.
- Prefer extending existing abstractions before introducing fork-only branches. Start from platform interfaces, backend selectors, registries, plugin hooks, model registries, and config gates.
- Keep vendor-specific logic isolated behind capability checks, backend registration, feature flags, or dedicated modules. Avoid scattering hardware conditionals across shared hot paths.
- Do not introduce unrelated runtime dependencies and do not couple this repo to external proprietary runtimes. Cross-repo experiments must stay isolated in dedicated environments or wrapper scripts.
- Avoid CUDA-only assumptions when editing shared code. Every hardware-specific optimization should have a clear fallback path, failure mode, and compatibility boundary.
- Favor changes that improve real AGI4S scenarios, not only synthetic microbenchmarks. Consider long-context serving, multimodal processing, structured output, reasoning or tool-calling flows, streaming latency, and scheduler stability.
- When changing kernels, memory management, schedulers, attention backends, or distributed execution, include a focused validation plan covering correctness, performance impact, and regression risk.
- If a change is unlikely to be upstreamed, keep the delta local and explicit: isolate names, config flags, docs, and tests so the fork-specific behavior is easy to maintain.
- Follow the build, test, and contribution rules already defined in the root AGENTS.md. Do not duplicate them here.

## Good Default Approach

1. Identify whether the task is about hardware enablement, AGI4S workload optimization, or generic upstream maintenance.
2. Find the narrowest existing extension point before modifying shared execution paths.
3. Keep the implementation merge-safe by minimizing invasive renames and preserving public behavior for non-target platforms.
4. Add or update targeted tests, benchmarks, and docs close to the touched subsystem.

## Useful Reference Areas

- docs/design/attention_backends.md for backend extension points.
- docs/design/mm_processing.md for multimodal processing behavior.
- docs/usage/v1_guide.md for supported runtime behaviors and compatibility expectations.
- docs/benchmarking/cli.md for benchmark entry points relevant to latency, throughput, multimodal, and structured output.
