# DiffSpec r007 evidence index

This directory contains the reproducible qualification runner. The immutable
raw output is retained at
`/data/codex-build-artifacts/sage-mate-mod-compat-20260904T053524Z/diffspec-r007`.

- Image: `sha256:6dec9e68eaa61d5a3297abc5006d939d5644aa203c16ef1f9af65fb54d60722b`
- Runtime source: `c78f55c7e4923da342f2fc52c2cb509c150e5363`
- Wheel SHA256: `2028172d18ac978fcfdb78e7192ec794641a517222a95a3eba888175b3d6aeba`
- Draft: `VirVen/Qwen3.5-27B-EAGLE3-v2`, checkpoint SHA256
  `a57cefc45874197a24dd2a092cfd0d0f7d6a2f2cca156d09f2d2f4a56dc4e5be`
- Target: Qwen3.8-27B, BF16, TP4, PP1, FULL_DECODE_ONLY graph
- Result: functional compatible, performance degraded; 103/534 draft tokens
  accepted (19.29%)
- Steady TTFT P50/P95: 0.459/0.469 s
- Steady latency P50/P95: 0.744/3.990 s
- Steady output throughput P50/P95: 14.00/14.24 tok/s
- Target-only output throughput P50/P95: 47.72/56.97 tok/s
- Rollback: baseline image `sha256:de1742dd6a1bc7ed1cbfff78d508ffa8ac769e58518d4e04d35a5d8203b88252`
  healthy; exact output `DIFFSPEC_ROLLBACK_OK`

Raw files include runtime identity, metrics before/after, service log, NPU
snapshots, both 10-request benchmarks, qualification/concurrency/cancellation,
26-test contract output and rollback identity/output.
