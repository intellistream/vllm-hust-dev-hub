#!/usr/bin/env bash
# sync-env.sh — Propagate the canonical token .env (this repo) to all sibling repos.
#
# Usage:
#   bash scripts/sync-env.sh            # dry-run (show diff)
#   bash scripts/sync-env.sh --apply    # actually copy
#
# The dev-hub .env is the SINGLE SOURCE OF TRUTH for secrets/tokens.
# Repos that also carry workstation-specific config (e.g. vllm-hust-workstation)
# will have their token lines patched in-place, preserving all other settings.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEV_HUB_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
SOURCE_ENV="$DEV_HUB_DIR/.env"
HOME_DIR=$(dirname "$DEV_HUB_DIR")

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

# Token keys managed by dev-hub .env (exact list)
TOKEN_KEYS=(
    GITHUB_TOKEN
    HF_ENDPOINT
    HF_TOKEN
    PYPI_TOKEN
    TAVILY_TOKEN
    CLOUDFLARE_ACCOUNT_ID
    CLOUDFLARE_ZONE_ID
    CLOUDFLARE_EMAIL
    CLOUDFLARE_GLOBAL_API_KEY
    CLOUDFLARE_BOOTSTRAP_TOKEN
    CLOUDFLARE_API_TOKEN
    VLLM_HUST_API_BASE_URL
    VLLM_HUST_API_KEY
)

# Target repos that should receive the full token .env (identical copy)
FULL_COPY_TARGETS=(
    "$HOME_DIR/SAGE"
)

# Target repos that merge tokens into their own .env (patch token lines only)
MERGE_TARGETS=(
    "$HOME_DIR/vllm-hust-workstation"
    "$HOME_DIR/sage-faculty-twin"
)

if [[ ! -f "$SOURCE_ENV" ]]; then
    echo "ERROR: source .env not found at $SOURCE_ENV" >&2
    exit 1
fi

echo "=== Source: $SOURCE_ENV ==="
echo ""

# --- Full copy targets ---
for target_dir in "${FULL_COPY_TARGETS[@]}"; do
    target_env="$target_dir/.env"
    if [[ ! -d "$target_dir" ]]; then
        echo "SKIP (dir missing): $target_dir"
        continue
    fi
    if [[ -f "$target_env" ]] && diff -q "$SOURCE_ENV" "$target_env" >/dev/null 2>&1; then
        echo "OK   (identical): $target_env"
    else
        echo "DIFF $target_env"
        if $APPLY; then
            cp "$SOURCE_ENV" "$target_env"
            echo "  -> copied"
        else
            diff --color=auto "$SOURCE_ENV" "$target_env" 2>/dev/null || true
        fi
    fi
done

echo ""

# --- Merge targets (patch token lines in-place) ---
for target_dir in "${MERGE_TARGETS[@]}"; do
    target_env="$target_dir/.env"
    if [[ ! -d "$target_dir" ]]; then
        echo "SKIP (dir missing): $target_dir"
        continue
    fi
    if [[ ! -f "$target_env" ]]; then
        echo "WARN (no .env): $target_dir — skipping merge target"
        continue
    fi

    all_match=true
    for key in "${TOKEN_KEYS[@]}"; do
        src_val=$(grep "^${key}=" "$SOURCE_ENV" 2>/dev/null | head -1 || true)
        tgt_val=$(grep "^${key}=" "$target_env" 2>/dev/null | head -1 || true)

        if [[ -z "$src_val" ]]; then
            continue  # key not in source, skip
        fi

        if [[ "$src_val" != "$tgt_val" ]]; then
            all_match=false
            echo "DIFF [$key] in $target_env"
            echo "  src: $src_val"
            echo "  tgt: ${tgt_val:-<missing>}"
            if $APPLY; then
                if [[ -n "$tgt_val" ]]; then
                    # Patch existing line
                    sed -i "s|^${key}=.*|${src_val}|" "$target_env"
                else
                    # Append missing key
                    echo "$src_val" >> "$target_env"
                fi
                echo "  -> patched"
            fi
        fi
    done

    if $all_match; then
        echo "OK   (all tokens match): $target_env"
    fi
done

echo ""
if $APPLY; then
    echo "Done. All .env files synced."
else
    echo "Dry-run complete. Re-run with --apply to make changes."
fi
