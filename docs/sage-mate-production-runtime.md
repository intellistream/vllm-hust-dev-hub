# Sage Mate production runtime profile

This profile keeps three identities separate. They must never be collapsed into
one `v0.23.0` label:

1. **Compatibility base**: the official vLLM Ascend `0.23.0` ARM64/openEuler
   runtime (CANN 9.1.0, Torch 2.10.0, torch-npu 2.10.0.post4 and
   triton-ascend 3.2.2).
2. **Active source snapshots**: the exact vLLM-HUST core and
   vllm-ascend-hust plugin commits in
   `config/vllm-ascend-production-lock.json`. The plugin's
   `verified_core_commit` must equal the locked core commit.
3. **Built artifact**: the derived image ID/digest, build timestamp and OCI
   labels produced from that exact pair.

The approved 2026-09-01 profile pins core
`ba07e4a48fc951300d97eb506217dd530583dea3` and the merged HUST plugin-main
snapshot `6f4c701573cc45c744aac136b524bd1742964deb`. Its source versions are
`0.23.1rc0.dev2625+gba07e4a4` and
`0.0.dev20260901+g6f4c70157`. A later moving `main` is not silently substituted:
the pair changes only through a reviewed lock update and the full image/NPU
acceptance gate.

## Lock and image contract

`config/vllm-ascend-production-lock.json` is the source of truth for:

- repository, commit and source-version identity for core and plugin;
- plugin verified-core relationship;
- compatibility base and package/toolchain versions;
- official base image tag and immutable digest;
- derived image tag.

The derived tag is descriptive:

```text
sage-mate/vllm-ascend-hust:ascend0.23.0-core-<core8>-plugin-<plugin8>
```

Reproducibility relies on the image ID/digest and OCI labels, not the tag. The
build writes `org.opencontainers.image.created`,
`org.opencontainers.image.revision`, repository/commit/source-version labels
for both source trees, compatibility-base/package labels and the lock schema.
The build also verifies package metadata and plugin entry points inside the
candidate image.

Build only from clean, exact checkouts:

```bash
scripts/build_locked_vllm_ascend_image.sh
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

