#!/usr/bin/env bash
# install_ascend_benchmark_root_helper.sh — Delegate to vllm-ascend-hust benchmark install script.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEV_HUB_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$DEV_HUB_ROOT/.." && pwd)"
VLLM_ASCEND_HUST_REPO="${VLLM_ASCEND_HUST_REPO:-$WORKSPACE_ROOT/vllm-ascend-hust}"
INSTALL_SCRIPT="$VLLM_ASCEND_HUST_REPO/scripts/install_ascend_benchmark_root_helper.sh"

if [[ ! -f "$INSTALL_SCRIPT" ]]; then
  echo "Ascend benchmark root helper installer not found: $INSTALL_SCRIPT" >&2
  echo "Set VLLM_ASCEND_HUST_REPO to the vllm-ascend-hust checkout, then rerun this command." >&2
  exit 1
fi

exec bash "$INSTALL_SCRIPT" "$@"