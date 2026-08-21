#!/usr/bin/env bash
set -euo pipefail

# First-boot setup for a maistro-engine sbx sandbox (run by the kit's install
# command, inside the microVM). Idempotent — safe to re-run.
#
# Expects (via `sbx secret set` or the environment at create time):
#   LITELLM_BASE_URL   — the EXTERNAL LiteLLM gateway, no trailing /v1
#   LITELLM_VIRTUAL_KEY — a scoped virtual key issued by that gateway
#   GITHUB_TOKEN        — optional; only needed for `maistro-rsi run --open-prs`

PERSIST=/etc/sandbox-persistent.sh
MARKER="# maistro-engine-setup"

info() { echo "[maistro-setup] $*"; }

# ── 1. Wait for the sandbox's private Docker daemon ─────────────────────────
info "Waiting for the private docker daemon..."
for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 2
done
docker info >/dev/null 2>&1 || { echo "docker daemon never came up" >&2; exit 1; }

# ── 2. Load preseeded images (keeps runtime egress = GitHub + LiteLLM only) ─
for tar in /opt/preseed/*.tar; do
    [ -e "$tar" ] || continue
    info "docker load < $tar"
    docker load -i "$tar"
done

# ── 3. Persist env for every future shell/exec in this sandbox ──────────────
if ! grep -q "$MARKER" "$PERSIST" 2>/dev/null; then
    info "Writing $PERSIST"
    base="${LITELLM_BASE_URL:-}"
    base="${base%/}"; base="${base%/v1}"
    key="${LITELLM_VIRTUAL_KEY:-${LITELLM_API_KEY:-${LITELLM_MASTER_KEY:-}}}"
    {
        echo "$MARKER"
        # Every alias set to the same value: builders reads LITELLM_URL +
        # LITELLM_MASTER_KEY, evolve reads LITELLM_BASE_URL + LITELLM_API_KEY/
        # LITELLM_VIRTUAL_KEY, LiteLLMSettings reads LITELLM_BASE_URL +
        # LITELLM_MASTER_KEY. Base is bare (no /v1) — callers append their own.
        echo "export LITELLM_BASE_URL='${base}'"
        echo "export LITELLM_URL='${base}'"
        echo "export LITELLM_PROXY_URL='${base}'"
        echo "export LITELLM_MASTER_KEY='${key}'"
        echo "export LITELLM_PROXY_KEY='${key}'"
        echo "export LITELLM_API_KEY='${key}'"
        echo "export LITELLM_VIRTUAL_KEY='${key}'"
        # Nested RSI test containers: preseeded image + a TTL long enough for
        # the 900s test window (containers run `sleep $SANDBOX_TIMEOUT`).
        echo "export SANDBOX_IMAGE='maistro-engine-tests:latest'"
        echo "export SANDBOX_TIMEOUT='3600'"
    } >> "$PERSIST"
fi

# ── 4. git-over-https auth (ssh/git protocol is blocked by the sbx proxy) ───
if [ -n "${GITHUB_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
    info "Configuring gh git credential helper"
    gh auth setup-git 2>/dev/null || true
fi

# ── 5. RSI workspace root (validate_workspace_path allowlist) ───────────────
mkdir -p /tmp/maistro-workspace

info "Setup complete."
