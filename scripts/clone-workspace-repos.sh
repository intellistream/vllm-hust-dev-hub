#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_BASE_DIR="$(cd -- "$ROOT_DIR/.." && pwd)"
CLONE_JOBS="${CLONE_JOBS:-4}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required but was not found in PATH" >&2
  exit 1
fi

if [[ ! "$CLONE_JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "CLONE_JOBS must be a positive integer" >&2
  exit 1
fi

# Default to HTTPS so the bootstrap works without requiring GitHub SSH setup.
# Keep upstream comparison repos under reference-repos/ rather than as top-level siblings.
REPOS=(
  "vllm-hust|https://github.com/intellistream/vllm-hust.git"
  "vllm-hust-workstation|https://github.com/intellistream/vllm-hust-workstation.git"
  "vllm-hust-website|https://github.com/intellistream/vllm-hust-website.git"
  "vllm-hust-docs|https://github.com/intellistream/vllm-hust-docs.git"
  "vllm-ascend-hust|https://github.com/intellistream/vllm-ascend-hust.git"
  "reference-repos/vllm|https://github.com/vllm-project/vllm.git"
  "reference-repos/sglang|https://github.com/sgl-project/sglang.git"
  "reference-repos/vllm-ascend|https://github.com/vllm-project/vllm-ascend.git"
  "EvoScientist|https://github.com/intellistream/EvoScientist.git"
  "vllm-hust-benchmark|https://github.com/intellistream/vllm-hust-benchmark.git"
)

clone_one() {
  local relative_path="$1"
  local repo_url="$2"
  local destination="$TARGET_BASE_DIR/$relative_path"

  mkdir -p "$(dirname -- "$destination")"

  if [[ -e "$destination" ]]; then
    echo "[skip] $relative_path already exists"
    return 0
  fi

  echo "[clone] $relative_path <- $repo_url"
  git clone "$repo_url" "$destination"
}

running_jobs=0
failures=0

for entry in "${REPOS[@]}"; do
  relative_path="${entry%%|*}"
  repo_url="${entry#*|}"

  clone_one "$relative_path" "$repo_url" &
  running_jobs=$((running_jobs + 1))

  if (( running_jobs >= CLONE_JOBS )); then
    if ! wait -n; then
      failures=$((failures + 1))
    fi
    running_jobs=$((running_jobs - 1))
  fi
done

while (( running_jobs > 0 )); do
  if ! wait -n; then
    failures=$((failures + 1))
  fi
  running_jobs=$((running_jobs - 1))
done

if (( failures > 0 )); then
  echo "Completed with $failures failed clone job(s)" >&2
  exit 1
fi

echo "All repository clone jobs finished successfully"