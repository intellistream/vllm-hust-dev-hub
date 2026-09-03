# Qwen3.8 native hybrid-cache migration

## Source and artifact identity

- Checkpoint: `Qwen/Qwen3.8-27B`, official revision
  `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`.
- Model backbone: `Qwen3_5ForConditionalGeneration`, BF16; 48 Gated DeltaNet
  layers and 16 full-attention layers. This is not a renamed older checkpoint.
- Core: `762f85b311fbab0bcf8921dd216f5093cd58b9b8`.
- Plugin snapshot: `4e57439e58ed3d78e675f9fd7b4614fb183c5394`, incorporating
  HUST main `1d2f1f87a7449cd86fd6c2946174224ee81def52` and official Ascend
  snapshot `6d02e22f078e59eb4b7947a887116151ad8eb100`.
- Package: `0.25.1rc1+hust.20260903.4`. The final commits add lint-only
  formatting to the already exercised `164860f3` cache implementation.

## Failure and forward fix

The original plugin's `LHBNC`-only cache capability rejected the mixed HNC
shapes before graph compilation. Simply advertising another layout is unsafe:
native paged attention and GDN kernels require dense state planes, while the
standardized core allocator returns block-interleaved views. The core Mamba
binder also expects raw pages, not already-unpacked native states.

The plugin now accepts layer-compact `LBHNC` pool placement for this path and
adapts core-owned offsets and pool sizes to contiguous native state planes at
initialization. Conv/key/value and conv/SSM/padding use identical plane
boundaries across aliased pools. Different block IDs remain disjoint; the
same block deliberately aliases states across owning groups. Total allocated
cache bytes are unchanged. No per-token copy or eager-mode override is added.

Invalid plane boundaries, partial overlaps, interleaved layers, unsupported
state counts and out-of-bounds descriptors fail before device allocation.
Native tuple binding validates state count, shape, dtype, contiguity and block
count; raw tensor binding still delegates to the core implementation.
The ordinary homogeneous `LHBNC` path is retained.

## Build provenance

The Python source and SCM package metadata were rebuilt in an isolated Git
worktree using `setup.py build_py` and `setup.py bdist_wheel --skip-build`.
Native binaries came from the already-verified `.20260902.9` wheel with SHA256
`2a83aef9bf81ef659338b82ba5ffbb570886e8c8238867352b58d4a05fd01e04`.
There is no source delta in `csrc`, `cmake`, `CMakeLists.txt`, `setup.py`, or
`requirements.txt` relative to `124826b8`; these are unchanged native build
inputs. All Python package sources were regenerated, not copied into a live
container. The resulting wheel hash is recorded in the production lock.

The standard `scripts/build_locked_vllm_ascend_image.sh` verifies the clean
core/plugin pair, the verified-core declaration and every wheel hash, then
builds an immutable image with matching labels and runtime receipt. The older
GLM-serving image is retained as an operational rollback, not a final model
migration result.

Final-wheel verification compares all 532 tracked Python sources with the
selected commit and all 1,199 native artifact members with the previously
verified wheel. Wheel SHA256:
`f13964eaf1f2b2edde43365533298b9054d2ae9dd988b41eba8c5eac387e5549`.
The image tag is
`sage-mate/vllm-ascend-hust:core-762f85b3-plugin-4e57439e-hybrid4-cann9.1`.

For a Python-only rebuild, first require an empty Git diff of native inputs
against the source commit of the hash-pinned native wheel. In an isolated
worktree using the same locked toolchain, retain those verified native build
outputs and regenerate Python sources and SCM metadata:

```bash
COMPILE_CUSTOM_KERNELS=1 SOC_VERSION=ascend910b1 python3 setup.py build_py
COMPILE_CUSTOM_KERNELS=1 SOC_VERSION=ascend910b1 python3 setup.py bdist_wheel --skip-build --dist-dir /path/to/artifacts
```

Do not use `--skip-build` for a changed native source or different toolchain.
Compare every Python file and native artifact in the produced wheel before
recording its hash in the lock. No files are patched inside the live container.

## Model deployment contract

Model paths, ports, physical device allocation and secrets belong to the
deployment's ignored environment, not Python code. This acceptance uses
physical NPU0–3 and TP4; other machines must reserve their own devices explicitly.
Set the checkpoint path and served ID to the verified Qwen snapshot. The tested
contract is BF16 weights/cache, 32,768 context, 4,096 batched tokens, eight
sequences, memory utilization0.75, requested kernel block size128, async scheduling, chunked
prefill on, prefix caching off, DP1 and FULL_DECODE_ONLY graphs. Extra flags:

```text
--language-model-only --reasoning-parser qwen3
--enable-auto-tool-choice --tool-call-parser qwen3_coder
--default-chat-template-kwargs {"enable_thinking":false,"preserve_thinking":false}
```

Application deep requests explicitly enable the model's native thinking;
ordinary requests explicitly disable it. Native reasoning support does not
imply MTP speculative decoding is active. This is a text-only acceptance, not
a claim that vision or tool execution has been exercised.

The hybrid-cache normalizer resolves the attention page to1536tokens at startup
and pads Mamba pages by0.97% so attention/state page byte sizes agree. Do not
confuse the requested128-token kernel block with the resolved hybrid page size.

## Validation scope

Eleven isolated CPU tests pass for allocation, aliasing, block isolation,
invalid-descriptor rejection and native/raw Mamba binding. Run:

```bash
python -m pytest -q --confcutdir=tests/ut/worker \
  tests/ut/worker/test_hybrid_cache.py \
  tests/ut/worker/test_native_mamba_binding.py
```

The full existing UT harness has a separate CPU-only collection problem:
its mocked `torch_npu`/`triton.runtime` modules are incompatible with the
installed Triton driver discovery. This is not counted as a successful test.

Hardware gate: four physical Ascend 910B2 devices, TP4, BF16, text-only
loading, `FULL_DECODE_ONLY`, capture sizes 1/2/4/8, 32,768-token configured
window, eight sequences. Native speculative decoding and prefix caching are
not enabled in the initial migration. Distributed cache transfer, hidden-state
cache connectors and additional hybrid architectures are outside this gate.
The final-image startup/chat/cold-restart results are recorded below.

## Final-image acceptance (2026-09-03)

Evidence class: `existing-server-probe`, not a throughput or model-quality
benchmark. Final image ID:
`sha256:de1742dd6a1bc7ed1cbfff78d508ffa8ac769e58518d4e04d35a5d8203b88252`.
OCI build-start time:2026-09-03T07:37:50Z. The managed replacement container
`733db360b8cdbe57a0d92727ae69e091fbfe5e80c8a029560f4266b7de7c008b`
started at07:46:21Z and passed health at07:51:46Z without an automatic restart.
This was a service/container cold restart with the existing model files and
compilation caches, not a cache-cleared compile-time benchmark.

The standard verifier passed `/health`, `/v1/models`, a strict real `OK`
completion, installed import origins, graph mode and physical NPU0–3 mapping.
Receipt ID:`deploy-0c30f1e4f2b63578bd43`.
Additional direct-serving checks:

| Probe | Result |
| --- | --- |
| Normal arithmetic | Correct391 plus verification sentence;1.50s;0reasoning tokens |
| Native thinking | Correct391 plus verification sentence;3.83s;119reasoning tokens |
| Stream | Multiple content deltas, normal stop and DONE;TTFT0.327s,total1.23s |
| Cancel | Disconnected after first content at0.316s; subsequent requests succeed |
| Two concurrent requests | Both correct, normal stop;1.68s/1.70s |
| Queue after cancel/concurrency | Running0,waiting0 |

No device mapping or service operation targeted NPU4–7. Their independent
owner restarted/removed its own containers during the audit, so a blanket
claim that those external container IDs stayed constant would be incorrect.
The OpenAI proxy was not restarted. Previous Qwen image5e7f82c7 and its private
environment backup remain available for managed rollback; no eager fallback
or model downgrade was used.

Public application normal QA also returned a real model answer and two Support
sources (server20.84s,client26.27s). Public deep QA is **not** marked passed:
one client stalled before delivery, a subsequent request logged200 at the app
but timed out awaiting response headers, and another resolved Cloudflare edge
returned502. Local engine health and real native completions remained healthy.
These transport failures remain explicit limits of this acceptance, not reasons
to hide failures or downgrade the model. This integration is a tested source
and deployment snapshot, not certification of Cloudflare availability.

Local application deep QA passed in23.28s with one native model call, no retry
or cache hit, three Support sources and five knowledge hits. This verifies the
application-to-engine reasoning path separately from the failed public transport.
