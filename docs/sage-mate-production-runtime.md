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

The approved current-main candidate pins core
`7c82451c03818d23746c962c173ffb1dbc78891b` and plugin
`59553edb222cafe7919d38c308db57ec7149353a`. Its installed package versions are
`0.28.1rc1.dev279+g7c82451c0.empty` and
`0.25.1rc1+hust.20260902.6`, with Torch `2.13.0+cpu`, torch-npu
`2.13.0rc1`, NumPy `2.2.6`, and source-built Triton Ascend
`3.6.0+gitb52af7fc` from vLLM-HUST/triton-ascend-hust main commit
`b52af7fc9a0377c6ed527a88a30df719874eeba9`. The Triton wheel keeps the
upstream-supported NumPy interval `>=1.26.4,<2.3`, which permits the locked
NumPy 2.2.6 required by the active OpenCV 5 dependency while rejecting the
incompatible NumPy 2.3 line. A later moving
`main` is not silently substituted:
the pair changes only through a reviewed lock update and the full image/NPU
acceptance gate.

The plugin version is deliberately governed by the annotated HUST tag
`v0.25.1rc1+hust.20260902.6`. Official current `main` is not descended from the
newer v0.20-v0.25 release branches, so an unconstrained `git describe` resolves
through v0.19 even when all official tags are present. Build-time version
resolution therefore fails closed for shallow clones, missing Git metadata,
missing tags, or stale versions below v0.23. The lock records the exact plugin
commit independently from the tag. `v0.23.0` remains the latest stable
compatibility-filesystem baseline; it is not the active core package version.

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

Build only from clean, exact checkouts:

```bash
scripts/build_locked_vllm_ascend_image.sh
```

Override the artifact directory only when mirroring the exact same files:

```bash
VLLM_ASCEND_ARTIFACT_DIR=/secure/mirror scripts/build_locked_vllm_ascend_image.sh
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

The 2026-09-01 rollback artifact is deliberately retained outside the lock:
`sage-mate/vllm-ascend-hust:v0.23.0-newrepos-ba07e4a4-40f9834e`
(`sha256:6119514ab4f4a90e4ab35d38c12063a14c44cffda998fde18fb8f3a8a8582478`).
Do not delete it as part of routine cleanup.
