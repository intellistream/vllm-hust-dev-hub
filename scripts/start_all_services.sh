#!/usr/bin/env bash
# start_all_services.sh — One-command startup for the full service stack.
#
# Brings up:
#   1. vLLM model service (via launch_ascend_model_service.sh)
#   2. sage-faculty-twin (my-twin) app + site proxy + Cloudflare tunnel
#   3. vllm-hust-workstation (Next.js frontend)
#
# Usage:
#   bash scripts/start_all_services.sh [--preset coder|w8a8] [--docker CONTAINER]
#                                        [--skip-model] [--skip-twin] [--skip-ws]
#                                        [--health-timeout SECS]
#
# Prerequisites:
#   - Docker container running with NPU devices (for model service)
#   - Cloudflare tunnel systemd unit configured with token-based ExecStart
#     (see sage-faculty-twin-tunnel.service)
#   - sagevdb C extension built for the correct Python version
#     (cd ~/sageVDB && bash build.sh with Python3_EXECUTABLE set)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── defaults ────────────────────────────────────────────────────────────────
PRESET="${PRESET:-coder}"
DOCKER_CONTAINER="${DOCKER_CONTAINER:-vllm_hust_ws_21rc}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-600}"
SKIP_MODEL=0
SKIP_TWIN=0
SKIP_WS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preset)       PRESET="$2"; shift 2 ;;
    --docker)       DOCKER_CONTAINER="$2"; shift 2 ;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
    --skip-model)   SKIP_MODEL=1; shift ;;
    --skip-twin)    SKIP_TWIN=1; shift ;;
    --skip-ws)      SKIP_WS=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

ok()   { echo -e "\033[32m[OK]\033[0m   $*"; }
warn() { echo -e "\033[33m[WARN]\033[0m $*"; }
fail() { echo -e "\033[31m[FAIL]\033[0m $*"; }
step() { echo -e "\n\033[1;34m━━━ $* ━━━\033[0m"; }

ERRORS=0

# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Model service
# ═══════════════════════════════════════════════════════════════════════════
if (( SKIP_MODEL == 0 )); then
  step "1/3  Model service (preset=$PRESET, docker=$DOCKER_CONTAINER)"

  # Check if already healthy
  if curl -fsS -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    ok "Model service already healthy on :8000"
  else
    echo "Launching model service..."
    bash "$SCRIPT_DIR/launch_ascend_model_service.sh" \
      --preset "$PRESET" \
      --docker "$DOCKER_CONTAINER" \
      --health-timeout "$HEALTH_TIMEOUT" \
      --no-health-check &
    LAUNCH_PID=$!

    echo "Waiting for health check (timeout=${HEALTH_TIMEOUT}s)..."
    DEADLINE=$((SECONDS + HEALTH_TIMEOUT))
    until curl -fsS -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; do
      if (( SECONDS >= DEADLINE )); then
        fail "Model service did not become healthy within ${HEALTH_TIMEOUT}s"
        ERRORS=$((ERRORS + 1))
        break
      fi
      sleep 5
    done
    if curl -fsS -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      ok "Model service healthy on :8000"
    fi
    wait "$LAUNCH_PID" 2>/dev/null || true
  fi
else
  warn "Skipping model service (--skip-model)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# Step 2: my-twin (sage-faculty-twin) services
# ═══════════════════════════════════════════════════════════════════════════
if (( SKIP_TWIN == 0 )); then
  step "2/3  my-twin services (app + site-proxy + tunnel)"

  TWIN_DIR="$HOME/sage-faculty-twin"
  if [[ -d "$TWIN_DIR" ]]; then
    cd "$TWIN_DIR"

    # Install + start all services (app, site-proxy, tunnel)
    bash tools/install_user_services.sh \
      --start \
      --with-site-proxy \
      --with-tunnel 2>&1 | tail -5

    sleep 3

    # Check app
    if systemctl --user is-active --quiet sage-faculty-twin-app.service; then
      ok "sage-faculty-twin-app: running"
    else
      fail "sage-faculty-twin-app: not running"
      journalctl --user -u sage-faculty-twin-app.service --no-pager -n 5 2>&1
      ERRORS=$((ERRORS + 1))
    fi

    # Check site proxy
    if systemctl --user is-active --quiet sage-faculty-twin-site.service; then
      ok "sage-faculty-twin-site: running"
    else
      fail "sage-faculty-twin-site: not running"
      ERRORS=$((ERRORS + 1))
    fi

    # Check tunnel
    if systemctl --user is-active --quiet sage-faculty-twin-tunnel.service; then
      ok "sage-faculty-twin-tunnel: running"
    else
      fail "sage-faculty-twin-tunnel: not running"
      journalctl --user -u sage-faculty-twin-tunnel.service --no-pager -n 3 2>&1
      ERRORS=$((ERRORS + 1))
    fi

    cd "$REPO_ROOT"
  else
    warn "sage-faculty-twin not found at $TWIN_DIR — skipping"
  fi
else
  warn "Skipping my-twin services (--skip-twin)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# Step 3: Workstation
# ═══════════════════════════════════════════════════════════════════════════
if (( SKIP_WS == 0 )); then
  step "3/3  Workstation (vllm-hust-workstation)"

  WS_DIR="$HOME/vllm-hust-workstation"
  if [[ -d "$WS_DIR" ]]; then
    export PATH="$HOME/miniconda3/bin:$PATH"
    cd "$WS_DIR"
    bash scripts/deploy_workstation.sh restart 2>&1 | tail -3

    sleep 3

    if systemctl --user is-active --quiet vllm-hust-workstation.service; then
      ok "vllm-hust-workstation: running on :3001"
    else
      fail "vllm-hust-workstation: not running"
      ERRORS=$((ERRORS + 1))
    fi

    cd "$REPO_ROOT"
  else
    warn "vllm-hust-workstation not found at $WS_DIR — skipping"
  fi
else
  warn "Skipping workstation (--skip-ws)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════
step "Summary"

echo "  Model service:  http://127.0.0.1:8000"
echo "  Workstation:    http://127.0.0.1:3001"
echo "  my-twin app:    http://127.0.0.1:55601"
echo "  External:       https://shuhao.sage.org.ai"
echo "  WS external:    https://ws.sage.org.ai"

if (( ERRORS > 0 )); then
  fail "$ERRORS service(s) failed to start"
  exit 1
else
  ok "All services started successfully"
fi
