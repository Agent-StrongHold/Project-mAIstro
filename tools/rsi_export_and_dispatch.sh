#!/usr/bin/env bash
set -euo pipefail
# Trusted orchestrator hand-off: take a completed RSI run's exported patches,
# commit them onto a throwaway export branch, and dispatch the rsi-harvest
# workflow to open one PR per improved file.
#
# Trust model (ADR-070126-6386 / ADR-093): this runs on the TRUSTED orchestrator
# (the host/job that spawned the isolated RSI container) — NOT inside that
# container, which never held a token. It needs a scoped token that can push a
# branch + dispatch a workflow; the workflow itself uses the built-in
# GITHUB_TOKEN to open (not merge) the PRs.
#
# Usage: tools/rsi_export_and_dispatch.sh <export_dir> [pr_base]
#   export_dir  a directory written by `maistro_rsi run --export-patches`
#   pr_base     base branch the PRs target (default: main)
#
# Note: GitHub only dispatches a workflow_dispatch workflow that exists on the
# default branch, so rsi-harvest.yml must be merged to that branch first.

EXPORT_DIR="${1:?usage: rsi_export_and_dispatch.sh <export_dir> [pr_base]}"
PR_BASE="${2:-main}"
REPO="${MAISTRO_RSI_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
SESSION="rsi-export/$(date -u +%Y%m%d-%H%M%S)"

[[ -f "$EXPORT_DIR/manifest.json" ]] || { echo "error: no manifest.json in $EXPORT_DIR" >&2; exit 2; }

# Commit the patches onto a fresh export branch off pr_base, under .rsi-exports/.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git clone -q --depth 1 --branch "$PR_BASE" "https://github.com/$REPO" "$tmp"
mkdir -p "$tmp/.rsi-exports"
cp "$EXPORT_DIR"/*.patch "$EXPORT_DIR/manifest.json" "$tmp/.rsi-exports/"
git -C "$tmp" checkout -q -b "$SESSION"
git -C "$tmp" add .rsi-exports
git -C "$tmp" -c user.email=rsi@maistro.local -c user.name=maistro-rsi \
    commit -qm "RSI export $SESSION ($(ls "$EXPORT_DIR"/*.patch | wc -l | tr -d ' ') promotion(s))"
git -C "$tmp" push -q -u origin "$SESSION"

# Dispatch the trusted harvest workflow (runs no agent code; opens the PRs).
gh workflow run rsi-harvest.yml --repo "$REPO" -f export_ref="$SESSION" -f pr_base="$PR_BASE"
echo "dispatched rsi-harvest for export_ref=$SESSION -> PRs targeting $PR_BASE"
