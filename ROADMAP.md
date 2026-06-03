# vLLM-HUST Performance Roadmap

This roadmap captures the next concrete steps after the current vLLM-HUST vs
official v0.18 performance investigation on Ascend.

## Current Status

- The current low-risk product change is in
  `vllm/v1/core/kv_cache_manager.py`: skip the redundant full-sequence fit
  check when the current scheduling step already covers the full remaining
  sequence.
- For the Qwen2.5-7B eager dummy benchmark on NPU 4
  (`input_len=1024`, `output_len=32`, `TP=1`), the patched current build ran at
  about `2.149 s` average latency.
- The following hypotheses were already ruled out for this workload:
  - Qwen2 rope fallback mismatch
  - rope-to-FIA layout mismatch
  - value-layout production mismatch
  - worker/model-runner explicit sync points as a new current-only hot-path
    regression
  - async scheduling as the primary source of the measured outer idle gap

## Next Steps

### 1. Quantify the KV admission optimization

Goal: decide whether the current `kv_cache_manager` fast path is worth keeping.

Tasks:

- run a strict A/B benchmark on the same workload with and without the fast
  path
- keep device, model, dtype, eager mode, and iteration counts identical
- if the delta is unstable, increase iteration count and compare median instead
  of only average latency
- keep the change only if the improvement is repeatable and behavior stays
  unchanged

## 2. Check host-side output cadence

Goal: test whether part of the remaining gap comes from output/stream cadence
rather than attention kernels.

Tasks:

- run the same short benchmark with a larger `stream_interval`
- compare latency impact against the default `stream_interval=1`
- if a non-default value helps, verify whether the gain holds on a slightly
  longer decode length

## 3. Probe frontend-to-engine output handling only if needed

Goal: instrument the outer control path only after the cheaper A/B checks above.

Tasks:

- add a small reversible probe around engine output delivery or scheduler
  update timing
- capture one current run and one official run under the same workload
- compare phase boundaries instead of reopening rope or attention layout work

## 4. Re-profile only after a candidate survives A/B

Goal: avoid expensive profiling passes until a candidate shows end-to-end value.

Tasks:

- once a candidate improves the short benchmark, collect a fresh same-spec
  TraceLoom profile pair
- verify whether prelude idle or late-loop idle actually drops
- reject candidates that only help micro timings but do not improve the final
  benchmark

## 5. Land and document the winning change

Goal: keep the fork merge-safe and evidence-driven.

Tasks:

- keep the final code delta focused and local
- record the benchmark command, results, and rejected hypotheses
- update nearby docs or notes only after the final change is chosen
