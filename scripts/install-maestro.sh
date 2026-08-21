#!/usr/bin/env bash
# maistro-engine — optional bootstrap helper (v1: clone + uv; no remote fetch yet).
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<org>/maistro-engine/main/scripts/install-maestro.sh | bash
# Prefer cloning the repo and running:
#   uv sync --extra bootstrap && uv run maistro-install
set -euo pipefail

info() { printf '%s\n' "[install-maestro] $*"; }

if ! command -v git >/dev/null 2>&1; then
  info "git is required."
  exit 1
fi

TARGET="${MAISTRO_CLONE_DIR:-$HOME/maistro-engine}"
BRANCH="${MAISTRO_BRANCH:-main}"

if [[ -d "$TARGET/.git" ]]; then
  info "Directory exists: $TARGET — pull latest? Run: cd \"$TARGET\" && git pull"
else
  info "Clone maistro-engine to $TARGET (set MAISTRO_CLONE_DIR to override)."
  info "Example: git clone --branch \"$BRANCH\" <YOUR_REPO_URL> \"$TARGET\""
  info "Then: cd \"$TARGET\" && uv sync --extra bootstrap && uv run maistro-install"
fi

if command -v uv >/dev/null 2>&1 && [[ -d "$TARGET" ]]; then
  (cd "$TARGET" && uv sync --extra bootstrap && info "Run: uv run maistro-install")
else
  info "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
fi
