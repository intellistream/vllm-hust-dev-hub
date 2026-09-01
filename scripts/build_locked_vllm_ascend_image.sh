#!/usr/bin/env bash
# Build the production Ascend image from a digest-pinned official base and
# verify that the source checkouts match the remote-reachable lock pair.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
lock_file="${VLLM_ASCEND_RUNTIME_LOCK:-$repo_root/config/vllm-ascend-production-lock.json}"
core_root="${1:-$repo_root/../vllm-hust}"
plugin_root="${2:-$repo_root/../vllm-ascend-hust}"

[[ -f "$lock_file" ]] || { echo "ERROR: runtime lock not found: $lock_file" >&2; exit 2; }

mapfile -t lock_values < <(python3 - "$lock_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)

print(lock["schema"])
print(f'{lock["base_image"]["reference"]}@{lock["base_image"]["digest"]}')
print(lock["vllm_core"]["repository"])
print(lock["vllm_core"]["commit"])
print(lock["vllm_ascend"]["repository"])
print(lock["vllm_ascend"]["commit"])
print(lock["image_tag"])
PY
)

(( ${#lock_values[@]} == 7 )) || { echo "ERROR: incomplete runtime lock" >&2; exit 2; }
lock_schema="${lock_values[0]}"
base_image="${lock_values[1]}"
core_repo="${lock_values[2]}"
core_commit="${lock_values[3]}"
plugin_repo="${lock_values[4]}"
plugin_commit="${lock_values[5]}"
image_tag="${VLLM_ASCEND_PRODUCTION_IMAGE_TAG:-${lock_values[6]}}"

verify_checkout() {
  local root="$1"
  local expected_repo="$2"
  local expected_commit="$3"
  local label="$4"
  [[ -d "$root/.git" || -f "$root/.git" ]] || { echo "ERROR: $label checkout not found: $root" >&2; exit 2; }
  [[ -z "$(git -C "$root" status --porcelain)" ]] || { echo "ERROR: $label checkout is dirty: $root" >&2; exit 2; }
  local actual_commit actual_repo
  actual_commit="$(git -C "$root" rev-parse HEAD)"
  actual_repo="$(git -C "$root" remote get-url origin)"
  [[ "$actual_commit" == "$expected_commit" ]] || {
    echo "ERROR: $label HEAD=$actual_commit, expected $expected_commit" >&2
    exit 2
  }
  case "$actual_repo" in
    "$expected_repo"|https://github.com/${expected_repo#git@github.com:}|https://github.com/${expected_repo#git@github.com:}.git) ;;
    *) echo "ERROR: $label origin=$actual_repo, expected $expected_repo" >&2; exit 2 ;;
  esac
}

verify_checkout "$core_root" "$core_repo" "$core_commit" "vLLM core"
verify_checkout "$plugin_root" "$plugin_repo" "$plugin_commit" "vLLM Ascend"

docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then
  sudo -n docker info >/dev/null 2>&1 || { echo "ERROR: Docker is unavailable" >&2; exit 2; }
  docker_cmd=(sudo -n docker)
fi

"${docker_cmd[@]}" image inspect "$base_image" >/dev/null 2>&1 || {
  echo "ERROR: digest-pinned base image is not local: $base_image" >&2
  exit 2
}

"${docker_cmd[@]}" build --pull=false --network host \
  --file "$repo_root/images/vllm-ascend-production/Dockerfile" \
  --tag "$image_tag" \
  --build-arg "BASE_IMAGE=$base_image" \
  --build-arg "RUNTIME_LOCK_SCHEMA=$lock_schema" \
  --build-arg "VLLM_CORE_REPOSITORY=$core_repo" \
  --build-arg "VLLM_CORE_COMMIT=$core_commit" \
  --build-arg "VLLM_ASCEND_REPOSITORY=$plugin_repo" \
  --build-arg "VLLM_ASCEND_COMMIT=$plugin_commit" \
  "$repo_root/images/vllm-ascend-production"

image_id="$("${docker_cmd[@]}" image inspect --format '{{.Id}}' "$image_tag")"
echo "[vllm-hust-image] tag=$image_tag"
echo "[vllm-hust-image] id=$image_id"
echo "[vllm-hust-image] core=$core_commit"
echo "[vllm-hust-image] plugin=$plugin_commit"
