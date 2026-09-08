# Sage Mate production runtime profile

This profile keeps three identities separate. They must never be collapsed into
one `v0.23.0` label:

1. **Compatibility base**: the official vLLM Ascend `0.23.0` ARM64/openEuler
   filesystem and CANN 9.1.0 runtime. Its Python packages are removed during
   the derived build and are not the active serving stack.
2. **Active source snapshots**: the exact vLLM-HUST core and
   vllm-ascend-hust plugin commits in
   `config/vllm-ascend-production-lock.json`. The plugin's
   `verified_core_commit` must equal the locked core commit.
3. **Built artifact**: the derived image ID/digest, build timestamp and OCI
   labels produced from that exact pair.

The verified production snapshot pins core
`d07d4c45e553c3d84ffdd7968aafb4906cdb5035` and merged plugin main
`a8d2294a4784218daaabb480aa84f10616f41f20`. Its installed package versions are
`0.28.1.post1.dev66+gd07d4c45e.empty` and
`0.25.1rc2.dev119+hust.20260903.4.ga8d2294a4`, with Torch `2.13.0+cpu`, torch-npu
`2.13.0rc1`, NumPy `2.2.6`, and source-built Triton Ascend
`3.6.0+gitb52af7fc` from vLLM-HUST/triton-ascend-hust main commit
`b52af7fc9a0377c6ed527a88a30df719874eeba9`. The Triton wheel keeps the
upstream-supported NumPy interval `>=1.26.4,<2.3`, which permits the locked
NumPy 2.2.6 required by the active OpenCV 5 dependency while rejecting the
incompatible NumPy 2.3 line. A later moving
`main` is not silently substituted:
the pair changes only through a reviewed lock update and the full image/NPU
acceptance gate.

The 2026-09-08 source freeze includes official vLLM `main`
`6c73b08dec2af5052288169663549687ba61f330` and official vLLM Ascend `main`
`b0c49dc7a884d3d343f6a556380f11b74191c3e8`; later upstream commits require a
new lock review and full acceptance gate. The plugin version is derived from complete tagged history rooted at the annotated
HUST tag `v0.25.1rc1+hust.20260903.4`; the exact merged-main commit remains the
authoritative identity. The earlier current-core KV-cache compatibility commits
are part of vLLM-HUST/vllm-ascend-hust `main`; the same generic change is also
tracked upstream as [vllm-project/vllm-ascend#15585](https://github.com/vllm-project/vllm-ascend/pull/15585).
Official current `main` is not descended from the
newer v0.20-v0.25 release branches, so an unconstrained `git describe` resolves
through v0.19 even when all official tags are present. Build-time version
resolution therefore fails closed for shallow clones, missing Git metadata,
missing tags, or stale versions below v0.23. The lock records the exact plugin
commit independently from the tag, and the plugin's
`.github/vllm-main-verified.commit` records the exact core pair. `v0.23.0` is the pinned
compatibility-filesystem baseline, not a claim about the latest official release
or the active core package version. The subsequent native hybrid-cache fix and
Qwen3.8 deployment are documented in [the migration record](qwen38-native-hybrid-cache.md);
they must not be conflated with the earlier upstream PR.

## Lock and image contract

`config/vllm-ascend-production-lock.json` is the source of truth for:

- repository, commit and source-version identity for core and plugin;
- plugin verified-core relationship;
- compatibility base and exact package/toolchain wheel filenames and SHA256;
- stable release baseline, active source profile, exact upstream snapshot
  commits and the HUST plugin source tag;
- exact runtime dependency wheels required by the synchronized core/plugin
  pair (including Transformers, FastAPI, Starlette, Hugging Face Hub, Triton,
  and pyelftools);
- official base image tag and immutable digest;
- derived image tag.

`branch: main` records the integration branch containing a verified immutable
snapshot, not permission to replace `commit` with a moving branch tip. Only
publish that declaration after the selected SHA is actually reachable from
canonical main. Before publishing parent gitlinks, verify both lock commits
against the parent checkouts and the plugin's verified-core declaration.

The derived tag is descriptive:

```text
sage-mate/vllm-ascend-hust:core-<core8>-plugin-<plugin8>-cann9.1
```

Reproducibility relies on the image ID/digest and OCI labels, not the tag. The
build writes `org.opencontainers.image.created`,
`org.opencontainers.image.revision`, repository/commit/source-version labels
for both source trees, stable-baseline/source-profile/package labels and the
lock schema.
The builder verifies every wheel hash before creating a temporary Docker
context. The image removes inherited release wheels and legacy metadata
shadowing, installs only the locked wheels, then validates real importlib
metadata, source versions, OpenAI server imports and plugin entry points. It
writes and verifies the direct dependency closure of the protected serving
packages independently from unrelated vendor packages inherited in the
official compatibility filesystem. Any missing or incompatible protected
dependency fails the image build; unrelated base-image `pip check` findings
remain visible as base-image debt and are not misreported as active-stack
failures. It
writes `/opt/vllm-hust-runtime/runtime-stack.json` and a normalized copy of the
v2 lock; it never manufactures `.dist-info` or injects `sitecustomize`.

## Responses API runtime controls

The launcher forwards the upstream-compatible Responses API controls directly
to the managed engine. Applications do not need to reimplement response state,
custom/freeform tool envelopes, or model-catalog augmentation in a product
proxy:

```text
VLLM_ENABLE_RESPONSES_API_STORE
VLLM_RESPONSES_API_STORE_MAX_ENTRIES
VLLM_RESPONSES_API_STORE_TTL_SECONDS
VLLM_OPENAI_MODELS_CATALOG_JSON
```

The store remains process-local and bounded. The catalog path must name a file
already present in an explicitly mounted runtime directory; the launcher does
not copy arbitrary host files or infer model capabilities. A reusable Qwen3.8
operator catalog is provided at
`config/model-catalogs/qwen3.8-27b.json`; the live server clamps its context and
auto-compaction fields to the served model configuration.

Build only from clean, exact checkouts:

```bash
scripts/build_locked_vllm_ascend_image.sh
```

Override the artifact directory only when mirroring the exact same files:

```bash
VLLM_ASCEND_ARTIFACT_DIR=/secure/mirror scripts/build_locked_vllm_ascend_image.sh
```

On hosts whose root filesystem cannot hold the multi-gigabyte immutable build
context, place only that temporary context on a larger local filesystem. The
builder still verifies every artifact against the lock before copying it:

```bash
VLLM_ASCEND_BUILD_CONTEXT_ROOT=/data/build-tmp scripts/build_locked_vllm_ascend_image.sh
```

## Deployment receipt

After `/health`, `/v1/models`, a real completion, physical NPU mapping and graph
mode pass, create a `vllm-hust.deployment-receipt/v1` receipt with
`scripts/deployment_receipt.py`. The public-safe receipt records the served
model, core/plugin commits, image tag, physical devices, parallelism, graph
mode, speculative state and sanitized import origins. The image ID/digest,
build time and package source versions are artifact provenance and must be
published alongside (for example by Workstation receipt schema v2 or the Sage
Mate stack endpoint); they are not inferred from the v1 receipt.

## Upgrade and rollback

1. Record the active container command, exact image ID, source gitlinks,
   deployment receipt, model, NPU ownership and successful completion.
2. Update core, plugin verified-core declaration, production lock, nested
   gitlinks and parent gitlink as one reviewed compatibility set.
3. Build a new immutable candidate; never mutate a running container.
4. Run import/entry-point tests, the repository test gate and isolated no-NPU
   preflight before reserving hardware.
5. On NPU, require target-model cold start, graph mode, health/models,
   completion, concurrent requests, cancellation and a second cold restart.
6. Switch only through the managed systemd/lock entrypoint. Do not create an
   unmanaged duplicate process.
7. If a production gate fails, restore the recorded previous image ID, lock
   values and gitlinks, then restart through the same managed entrypoint.

The latest-main pair passed Qwen3.8-27B TP4 graph-mode cold start twice on physical
NPU0-3, non-streaming and streaming completion, native thinking, two-request
concurrency, cancellation recovery, Sage workflow and public Support rendering.
The pre-promotion canary remains available as
`sage-mate/vllm-ascend-hust:core-88e606d0-plugin-d92617b0-canary1-cann9.1`.

The 2026-09-01 rollback artifact is deliberately retained outside the lock:
`sage-mate/vllm-ascend-hust:v0.23.0-newrepos-ba07e4a4-40f9834e`
(`sha256:6119514ab4f4a90e4ab35d38c12063a14c44cffda998fde18fb8f3a8a8582478`).
Do not delete it as part of routine cleanup.
