# ascend-runtime-manager

Lightweight manager for Ascend runtime setup and diagnostics.

## Why

This repository isolates system-level Ascend dependency management from runtime repos.
`vllm-hust` can call this manager so end users keep a single install entrypoint.

## Commands

- `hust-ascend-manager doctor`
- `hust-ascend-manager doctor --json`
- `hust-ascend-manager env --shell`
- `hust-ascend-manager setup --manifest manifests/euleros-910b.json --dry-run`
- `hust-ascend-manager setup --manifest manifests/euleros-910b.json --install-python-stack`
- `hust-ascend-manager setup --manifest manifests/euleros-910b.json --apply-system`

Default `euleros-910b` manifest includes:

- `conda config --add channels https://repo.huaweicloud.com/ascend/repos/conda/`
- `conda install ascend::cann-toolkit==8.5.0`
- `conda install ascend::cann-910b-ops==8.5.0`
- `conda install ascend::cann-nnal==8.5.0`

When a system step declares `requires_group: HwHiAiUser`, manager will run it via
`sg HwHiAiUser -c ...` automatically when needed.

`env --shell` is the source of truth for Ascend runtime exports. Runtime repos
should consume this output instead of carrying duplicated shell logic.

The design follows upstream vLLM's plugin philosophy: hardware-specific setup
and runtime adaptation should live outside the upstream core runtime path.

## Install

```bash
cd /home/shuhao/vllm-hust-dev-hub/ascend-runtime-manager
python -m pip install -e .
```

Or install from PyPI (recommended for teammates):

```bash
python -m pip install --upgrade hust-ascend-manager
```

## Publish

Local publish with token:

```bash
cd /home/shuhao/vllm-hust-dev-hub/ascend-runtime-manager
PYPI_TOKEN=pypi-xxxxx bash scripts/publish_pypi.sh
```

CI publish:

- set repository secret `PYPI_TOKEN`
- push a tag like `v0.1.0` or run workflow dispatch

## Notes

- `setup --apply-system` executes commands from manifest and may require sudo.
- Keep binary payloads out of this repository. Use internal mirrors/artifact stores.
- If your account was newly added to `HwHiAiUser`, re-login is still recommended.
