# Optimization Profile Manifests

## Goal

Operators select an optimization by name instead of manually coordinating
repository paths, Python entry-point groups, `VLLM_PLUGINS`, environment
forwarding, and JSON-encoded vLLM arguments.

```bash
./manage.sh restart --optimization bidkv
./manage.sh restart --optimization diffspec --draft-model /models/eagle3
./manage.sh restart --optimization latchmoe --offload-gb 14
```

## Repository contract

Each optimization repository owns `.vllm-hust/optimization.json`. The manifest
declares:

- a stable profile ID and repository directory name;
- the exact Python entry-point group and name;
- the Python source subdirectory;
- required or defaulted operator parameters;
- the deterministic `VLLM_PLUGINS` allowlist for the profile;
- environment defaults and forwarding keys/prefixes;
- additional vLLM arguments;
- known incompatible profiles.

The dev-hub resolver validates schema version 1, rejects unknown or missing
parameters, renders `${parameter}` placeholders, and emits shell-quoted
environment variables. Existing operator environment values override manifest
environment defaults. The manifest owns the exact `VLLM_PLUGINS` allowlist.
Existing `VLLM_ENGINE_EXTRA_ARGS_JSON` entries are appended after profile
arguments so explicit operator arguments remain last.

A named profile also owns its repository path. A stale
`VLLM_OPTIMIZATION_REPO_CONTAINER` from an earlier low-level launch cannot
redirect the selected profile to another repository. The resolver's explicit
`--container-repo` option remains available for controlled nonstandard
container layouts.

Each profile explicitly lists its vLLM plugins. This prevents an optimization
left installed by an earlier run from being discovered accidentally when the
operator switches profiles.

## Runtime flow

1. `manage.sh` resolves the named manifest from sibling repositories.
2. The resolver produces the generic `VLLM_OPTIMIZATION_*` contract.
3. The systemd environment records the resolved configuration.
4. When the exact entry point is absent, `VLLM_ENGINE_PYTHON` installs a
   repository snapshot into a launch-unique, container-local target. The
   engine prefix is never mutated and the target is removed when the service
   exits. Persistent pip caching is disabled for this transient installation.
5. Startup fails if installation does not register the declared group/name.
6. vLLM starts with the manifest's activation environment and arguments.

## Reproducible integration workspace

Before collecting container or NPU evidence, verify the exact three Draft PR
commits and require clean worktrees:

```bash
python3 scripts/verify_optimization_workspace.py \
  --workspace-root /workspace \
  --core-sha <core-pr-head> \
  --dev-hub-sha <dev-hub-pr-head> \
  --bidkv-sha <bidkv-pr-head> \
  --output /workspace/evidence/optimization-workspace.json
```

The command fails closed on a SHA mismatch or dirty repository and records the
resolved paths, branches, expected SHAs, actual SHAs, and cleanliness state.

## Compatibility policy

One optimization profile is supported per service instance. Use separate
container, port, device, and systemd-unit assignments for independent
experiments. Multi-profile activation remains disabled until a tested
compatibility matrix and deterministic argument/environment merge policy are
available.

## Migration

The existing low-level `VLLM_OPTIMIZATION_*` variables remain supported for
custom repositories and debugging. Profile selection is a convenience layer;
it does not remove the generic launcher contract.
