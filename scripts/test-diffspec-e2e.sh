#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${DIFFSPEC_PROFILE:-$ROOT_DIR/profiles/diffspec-smoke-npu1.env}"
ENV_NAME="${DIFFSPEC_CONDA_ENV:-vllm-hust-dev}"

: "${VLLM_HUST_API_KEY:?Set VLLM_HUST_API_KEY}"
: "${DIFFSPEC_TARGET_MODEL:?Set DIFFSPEC_TARGET_MODEL}"
: "${DIFFSPEC_DRAFT_MODEL:?Set DIFFSPEC_DRAFT_MODEL}"

profile_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); value=$0 } END { print value }' "$PROFILE"
}

PORT="$(profile_value VLLM_ENGINE_PORT)"
UNIT="$(profile_value VLLM_ENGINE_SYSTEMD_UNIT)"
SERVED_MODEL="$(profile_value VLLM_ENGINE_SERVED_MODEL_NAME)"

[[ -n "$PORT" ]] || { echo "Missing VLLM_ENGINE_PORT in $PROFILE" >&2; exit 1; }
[[ -n "$UNIT" ]] || { echo "Missing VLLM_ENGINE_SYSTEMD_UNIT in $PROFILE" >&2; exit 1; }
[[ -n "$SERVED_MODEL" ]] || { echo "Missing VLLM_ENGINE_SERVED_MODEL_NAME in $PROFILE" >&2; exit 1; }

cleanup() {
  VLLM_ENGINE_ENV_FILE="$PROFILE" "$ROOT_DIR/manage.sh" stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[1/6] Install core repositories and DiffSpec"
bash "$ROOT_DIR/scripts/quickstart.sh" \
  --install \
  --install-mode refresh \
  --install-scope plugins \
  --env-name "$ENV_NAME" \
  -y

echo "[2/6] Verify the DiffSpec entry point"
conda run -n "$ENV_NAME" python - <<'PY2'
from importlib.metadata import entry_points

matches = [
    entry
    for entry in entry_points(group="vllm.general_plugins")
    if entry.name == "diffspec"
]
assert len(matches) == 1, matches
assert matches[0].value == "diffspec.plugin:register", matches[0]
print(f"DiffSpec entry point: {matches[0].name} -> {matches[0].value}")
PY2

export VLLM_ENGINE_ENV_FILE="$PROFILE"
export VLLM_ENGINE_MODEL_PATH="$DIFFSPEC_TARGET_MODEL"

export VLLM_ENGINE_EXTRA_ARGS_JSON="$(
  python3 - "$DIFFSPEC_DRAFT_MODEL" <<'PY2'
import json
import sys

draft_model = sys.argv[1]
config = {
    "method": "eagle3",
    "model": draft_model,
    "num_speculative_tokens": 5,
    "enforce_eager": True,
    "draft_context_policy": "diffspec",
    "diffspec_verification_mode": "auto",
    "diffspec_chunk_size": 32,
    "diffspec_token_budget": 2048,
    "diffspec_retrieval_interval": 8,
    "diffspec_max_tree_nodes": 50,
    "diffspec_tree_threshold": 0.7,
    "diffspec_adaptive_profile": True,
    "diffspec_long_context_threshold": 49152,
    "diffspec_long_context_depth": 2,
}
print(
    json.dumps(
        [
            "--speculative-config",
            json.dumps(config, separators=(",", ":")),
            "--no-async-scheduling",
        ]
    )
)
PY2
)"

echo "[3/6] Start the DiffSpec service"
"$ROOT_DIR/manage.sh" restart

echo "[4/6] Wait for health"
healthy=0
for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null; then
    healthy=1
    break
  fi
  sleep 5
done

if [[ "$healthy" != "1" ]]; then
  journalctl --user -u "$UNIT" --no-pager -n 300 || true
  echo "DiffSpec service did not become healthy" >&2
  exit 1
fi

echo "[5/6] Send an OpenAI-compatible completion request"
response="$(
  curl -fsS "http://127.0.0.1:${PORT}/v1/completions" \
    -H "Authorization: Bearer ${VLLM_HUST_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"${SERVED_MODEL}\",
      \"prompt\": \"Explain speculative decoding in one sentence.\",
      \"max_tokens\": 16,
      \"temperature\": 0
    }"
)"

printf '%s' "$response" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
assert payload.get("choices"), payload
assert payload["choices"][0]["text"].strip(), payload
print(payload["choices"][0]["text"])
'

echo "[6/6] Verify DiffSpec activation logs"
logs="$(journalctl --user -u "$UNIT" --no-pager -n 500)"
case "$logs" in
  *"DiffSpec draft cache initialized"*) ;;
  *) echo "DiffSpec initialization log was not found" >&2; exit 1 ;;
esac
case "$logs" in
  *"DiffSpec verification mode"*) ;;
  *) echo "DiffSpec verification-mode log was not found" >&2; exit 1 ;;
esac

echo "DiffSpec E2E passed"
