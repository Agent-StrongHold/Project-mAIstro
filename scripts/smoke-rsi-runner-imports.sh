#!/usr/bin/env bash
# Artifact-level RSI runtime proof for the maistro-rsi-runner image (#346).
#
# The rsi-runner image exists so the ENTIRE self-improvement loop (agent, git,
# tests, coverage, fitness) executes inside it. Its runtime contract is the
# one tools/run_rsi_isolated.sh operates: the workspace venv for third-party
# dependencies, and the maistro source trees on PYTHONPATH for the workspace
# members the root meta-package does not install (maistro-rsi, maistro-evolve
# — the root pyproject depends on maistro-core and maistro-canvas, not them).
# The first #346 smoke attempt probed a bare `python -c "import maistro_rsi"`
# and failed twice over — the system interpreter first, then the venv, which
# never contained maistro-rsi (docs/testing/inventory-notes/
# claude-issue-346-smoke-tests.md).
#
# This script proves the built artifact, on the image alone:
#
#   1. The operator contract's exact environment — the venv activated and the
#      same PACKAGE_PATHS tools/run_rsi_isolated.sh exports — imports
#      maistro_rsi and maistro_evolve, the `python -m maistro_rsi run|evolve`
#      entrypoints' own imports.
#   2. A control image without the workspace FAILS the same probe, so the
#      probe cannot silently pass on an artifact that lost its runtime.
#
# The probe runs with --network=none and no mounts: the image is
# self-contained by design (the loop's only network egress is the gateway,
# attached at run time).
#
# Usage:
#   scripts/smoke-rsi-runner-imports.sh <image-ref> [control-image]
#
# Arguments:
#   <image-ref>       image to prove (required). `maistro-rsi-runner:ci` in CI.
#   [control-image]   must FAIL the probe; defaults to the digest-pinned
#                     python:3.12-slim base Dockerfile.rsi-runner builds from
#                     (already on the machine wherever this script runs: the
#                     docker-build job pre-pulls this Dockerfile's bases).
#
# Environment: none required.

set -euo pipefail

IMAGE="${1:?usage: smoke-rsi-runner-imports.sh <image-ref> [control-image]}"
CONTROL_IMAGE="${2:-python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704}"

# The operator contract, verbatim from tools/run_rsi_isolated.sh: the loop's
# entrypoints import the workspace members from these source trees, not from
# the venv. tests/test_image_boot_smokes.py holds the two lists equal so this
# cannot drift from the contract it mirrors.
PACKAGE_PATHS="packages/maistro-core/src:packages/maistro-evolve/src:packages/maistro-rsi/src:packages/maistro-bootstrap/src"

# The probe, passed through the environment so no quoting layer can rewrite it.
RSI_SMOKE_PROBE='import maistro_evolve, maistro_rsi
print("rsi runtime imports ok")'

# The proof itself: image contents only — no network, no mounts. --workdir is
# the image's own /workspace; the venv and the source trees are both inside it.
docker run --rm --network=none --workdir /workspace \
    -e PYTHONPATH="$PACKAGE_PATHS" \
    -e RSI_SMOKE_PROBE="$RSI_SMOKE_PROBE" \
    "$IMAGE" bash -c 'source /workspace/.venv/bin/activate && python -c "$RSI_SMOKE_PROBE"'

# The control: the same contract must FAIL on an image without the workspace
# (no /workspace, no venv), or the probe above proves nothing.
if docker run --rm --network=none \
    -e PYTHONPATH="$PACKAGE_PATHS" \
    -e RSI_SMOKE_PROBE="$RSI_SMOKE_PROBE" \
    "$CONTROL_IMAGE" bash -c 'source /workspace/.venv/bin/activate && python -c "$RSI_SMOKE_PROBE"' >/dev/null 2>&1; then
    echo "FAIL: the control image ($CONTROL_IMAGE) passed the RSI import probe" >&2
    echo "      -- the probe has no teeth; a workspace-less artifact would pass it" >&2
    exit 1
fi

# Record the tested artifact, so the evidence names what it describes.
echo "smoke: rsi runtime imports proven on $(docker image inspect --format '{{.Id}}' "$IMAGE")"
