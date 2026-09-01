#!/usr/bin/env bash
# Build the production Ascend image exclusively from digest- and hash-pinned
# inputs declared by the v2 runtime lock.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
lock_file="${VLLM_ASCEND_RUNTIME_LOCK:-$repo_root/config/vllm-ascend-production-lock.json}"
core_root="${1:-$repo_root/../vllm-hust}"
plugin_root="${2:-$repo_root/../vllm-ascend-hust}"

[[ -f "$lock_file" ]] || { echo "ERROR: runtime lock not found: $lock_file" >&2; exit 2; }

mapfile -t lock_values < <(python3 - "$lock_file" <<'PY'
import json
import sys

lock = json.load(open(sys.argv[1], encoding="utf-8"))
print(lock["schema"])
print(f'{lock["base_image"]["reference"]}@{lock["base_image"]["digest"]}')
print(lock["vllm_core"]["repository"])
print(lock["vllm_core"]["commit"])
print(lock["vllm_core"]["source_version"])
print(lock["vllm_core"]["package_version"])
print(lock["vllm_ascend"]["repository"])
print(lock["vllm_ascend"]["commit"])
print(lock["vllm_ascend"]["source_version"])
print(lock["vllm_ascend"]["package_version"])
print(f'{lock["compatibility"]["core_line"]}; {lock["compatibility"]["plugin_line"]}; CANN {lock["compatibility"]["cann"]}')
print(lock["runtime"]["artifact_directory"])
print(lock["image_tag"])
PY
)

(( ${#lock_values[@]} == 13 )) || { echo "ERROR: incomplete v2 runtime lock" >&2; exit 2; }
lock_schema="${lock_values[0]}"
base_image="${lock_values[1]}"
core_repo="${lock_values[2]}"
core_commit="${lock_values[3]}"
core_source_version="${lock_values[4]}"
core_package_version="${lock_values[5]}"
plugin_repo="${lock_values[6]}"
plugin_commit="${lock_values[7]}"
plugin_source_version="${lock_values[8]}"
plugin_package_version="${lock_values[9]}"
compatibility_base="${lock_values[10]}"
artifact_root="${VLLM_ASCEND_ARTIFACT_DIR:-${lock_values[11]}}"
image_tag="${VLLM_ASCEND_PRODUCTION_IMAGE_TAG:-${lock_values[12]}}"
build_created="${VLLM_ASCEND_BUILD_CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

verify_checkout() {
  local root="$1" expected_repo="$2" expected_commit="$3" label="$4"
  [[ -d "$root/.git" || -f "$root/.git" ]] || { echo "ERROR: $label checkout not found: $root" >&2; exit 2; }
  [[ -z "$(git -C "$root" status --porcelain)" ]] || { echo "ERROR: $label checkout is dirty: $root" >&2; exit 2; }
  local actual_commit actual_repo
  actual_commit="$(git -C "$root" rev-parse HEAD)"
  actual_repo="$(git -C "$root" remote get-url origin)"
  [[ "$actual_commit" == "$expected_commit" ]] || { echo "ERROR: $label HEAD=$actual_commit, expected $expected_commit" >&2; exit 2; }
  case "$actual_repo" in
    "$expected_repo"|"https://github.com/${expected_repo#git@github.com:}"|"https://github.com/${expected_repo#git@github.com:}.git") ;;
    *) echo "ERROR: $label origin=$actual_repo, expected $expected_repo" >&2; exit 2 ;;
  esac
}

verify_checkout "$core_root" "$core_repo" "$core_commit" "vLLM core"
verify_checkout "$plugin_root" "$plugin_repo" "$plugin_commit" "vLLM Ascend"

verified_core_file="$plugin_root/.github/vllm-main-verified.commit"
[[ -f "$verified_core_file" ]] || { echo "ERROR: vLLM Ascend verified-core declaration is missing" >&2; exit 2; }
verified_core="$(tr -d '[:space:]' < "$verified_core_file")"
[[ "$verified_core" == "$core_commit" ]] || { echo "ERROR: plugin verifies core=$verified_core, lock selects $core_commit" >&2; exit 2; }

[[ -d "$artifact_root" ]] || { echo "ERROR: artifact directory not found: $artifact_root" >&2; exit 2; }
mapfile -t artifacts < <(python3 - "$lock_file" <<'PY'
import json
import sys

lock = json.load(open(sys.argv[1], encoding="utf-8"))
for component in (lock["vllm_core"], lock["vllm_ascend"]):
    artifact = component["artifact"]
    print(f'{artifact["filename"]}\t{artifact["sha256"]}')
for name in ("torch", "torch_npu", "torchvision", "torchaudio", "triton_ascend"):
    artifact = lock["python_stack"][name]
    print(f'{artifact["filename"]}\t{artifact["sha256"]}')
for artifact in lock["runtime_dependencies"].values():
    print(f'{artifact["filename"]}\t{artifact["sha256"]}')
PY
)

build_context="$(mktemp -d /tmp/vllm-hust-image.XXXXXX)"
trap 'rm -rf "$build_context"' EXIT
mkdir -p "$build_context/artifacts"
for entry in "${artifacts[@]}"; do
  filename="${entry%%$'\t'*}"
  expected_sha="${entry#*$'\t'}"
  artifact="$artifact_root/$filename"
  [[ -f "$artifact" ]] || { echo "ERROR: locked artifact missing: $artifact" >&2; exit 2; }
  actual_sha="$(sha256sum "$artifact" | awk '{print $1}')"
  [[ "$actual_sha" == "$expected_sha" ]] || { echo "ERROR: artifact hash mismatch: $filename" >&2; exit 2; }
  cp "$artifact" "$build_context/artifacts/$filename"
done
cp "$lock_file" "$build_context/production-lock.json"
cp "$repo_root/images/vllm-ascend-production/Dockerfile" "$build_context/Dockerfile"
cp "$repo_root/images/vllm-ascend-production/install_runtime_metadata.py" "$build_context/install_runtime_metadata.py"

docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then
  sudo -n docker info >/dev/null 2>&1 || { echo "ERROR: Docker is unavailable" >&2; exit 2; }
  docker_cmd=(sudo -n docker)
fi
"${docker_cmd[@]}" image inspect "$base_image" >/dev/null 2>&1 || { echo "ERROR: digest-pinned base image is not local: $base_image" >&2; exit 2; }

"${docker_cmd[@]}" build --pull=false --network host \
  --file "$build_context/Dockerfile" --tag "$image_tag" \
  --build-arg "BASE_IMAGE=$base_image" \
  --build-arg "RUNTIME_LOCK_SCHEMA=$lock_schema" \
  --build-arg "VLLM_CORE_REPOSITORY=$core_repo" \
  --build-arg "VLLM_CORE_COMMIT=$core_commit" \
  --build-arg "VLLM_CORE_SOURCE_VERSION=$core_source_version" \
  --build-arg "VLLM_CORE_PACKAGE_VERSION=$core_package_version" \
  --build-arg "VLLM_ASCEND_REPOSITORY=$plugin_repo" \
  --build-arg "VLLM_ASCEND_COMMIT=$plugin_commit" \
  --build-arg "VLLM_ASCEND_SOURCE_VERSION=$plugin_source_version" \
  --build-arg "VLLM_ASCEND_PACKAGE_VERSION=$plugin_package_version" \
  --build-arg "VLLM_COMPATIBILITY_BASE=$compatibility_base" \
  --build-arg "BUILD_CREATED=$build_created" \
  "$build_context"

image_id="$("${docker_cmd[@]}" image inspect --format '{{.Id}}' "$image_tag")"
echo "[vllm-hust-image] tag=$image_tag"
echo "[vllm-hust-image] id=$image_id"
echo "[vllm-hust-image] core=$core_commit ($core_package_version)"
echo "[vllm-hust-image] plugin=$plugin_commit ($plugin_package_version)"
echo "[vllm-hust-image] install_mode=immutable-wheels"
echo "[vllm-hust-image] created=$build_created"
