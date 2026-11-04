#!/usr/bin/env bash
# Artifact-level Chromium proof for the maistro-engine-research image (#346).
#
# The research image's whole reason to exist is the browser surface
# (browser-use + Playwright + Chromium) split out of the API image — its own
# header calls it "the single largest remaining CVE source". A green build
# says the layers assemble; it does not say the browser is present or
# loadable. The first #346 smoke attempt got this wrong twice
# (docs/testing/inventory-notes/claude-issue-346-smoke-tests.md): probing
# `chromium --version` on PATH (exit 127 — Playwright never puts the browser
# on PATH) and then probing an interpreter that was not the venv's.
#
# This script proves the built artifact, on the image alone:
#
#   1. The image's venv Python imports Playwright and resolves the Chromium
#      binary through it (`p.chromium.executable_path`) — the same resolution
#      the RESEARCH web tool performs at run time.
#   2. The resolved binary exists at the configured PLAYWRIGHT_BROWSERS_PATH
#      and executes `--version` (check=True): the Chromium shared-library
#      layer actually loads, which a stripped X stack would fail.
#   3. A control image without the browser stack FAILS the same probe — so a
#      probe that lost its teeth (e.g. an import made optional) fails here
#      instead of silently passing on a browser-less artifact.
#
# The probe runs with --network=none, no mounts and a cleared PYTHONPATH, so
# nothing can arrive from outside the image.
#
# Usage:
#   scripts/smoke-research-chromium.sh <image-ref> [control-image]
#
# Arguments:
#   <image-ref>       image to prove (required). `maistro-engine-research:ci`
#                     in CI.
#   [control-image]   must FAIL the probe; defaults to the digest-pinned
#                     python:3.12-slim base Dockerfile.research builds from
#                     (already on the machine wherever this script runs: the
#                     same pin serves Dockerfile.rsi-runner, whose bases the
#                     docker-build job pre-pulls).
#
# Environment: none required.

set -euo pipefail

IMAGE="${1:?usage: smoke-research-chromium.sh <image-ref> [control-image]}"
CONTROL_IMAGE="${2:-python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704}"

CHROMIUM_PROBE='
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    executable = Path(p.chromium.executable_path)
    assert executable.is_file(), f"playwright resolved no chromium binary at {executable}"
    version = subprocess.run(
        [str(executable), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    print("chromium", version)
'

# The proof itself: image contents only — no network, no mounts, no PYTHONPATH
# assist. The image's own ENV resolves `python` to the lock-built venv and runs
# as the non-root user the entrypoint runs as.
docker run --rm --network=none -e PYTHONPATH= "$IMAGE" python -c "$CHROMIUM_PROBE"

# The control: the same probe must FAIL on an image without the browser stack,
# or the probe above proves nothing.
if docker run --rm --network=none -e PYTHONPATH= "$CONTROL_IMAGE" python -c "$CHROMIUM_PROBE" >/dev/null 2>&1; then
    echo "FAIL: the control image ($CONTROL_IMAGE) passed the chromium probe" >&2
    echo "      -- the probe has no teeth; a browser-less artifact would pass it" >&2
    exit 1
fi

# Record the tested artifact, so the evidence names what it describes.
echo "smoke: research chromium surface proven on $(docker image inspect --format '{{.Id}}' "$IMAGE")"
