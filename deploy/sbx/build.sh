#!/usr/bin/env bash
set -euo pipefail

# Build the maistro-engine sbx template + its preseed images.
#
# Run from anywhere; operates on the repo root. Requires a Docker daemon on
# the BUILD host (this is the one step with registry egress — the sandboxes
# themselves never pull).
#
# Usage:
#   ./deploy/sbx/build.sh                # build + `sbx template load` locally
#   PUSH_TAG=org/maistro-sbx:v1 ./deploy/sbx/build.sh   # build + push instead

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
PRESEED_DIR="$REPO_ROOT/deploy/sbx/template/preseed"
TEMPLATE_TAG="${TEMPLATE_TAG:-maistro-sbx-template:latest}"
TESTS_TAG="maistro-engine-tests:latest"

info() { echo "[sbx-build] $*"; }

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon not reachable" >&2; exit 1; }

mkdir -p "$PRESEED_DIR"

info "Building the nested test image ($TESTS_TAG)..."
docker build -f "$REPO_ROOT/deploy/sbx/template/Dockerfile.tests" -t "$TESTS_TAG" "$REPO_ROOT"

info "Pulling the default sandbox base image (python:3.12-slim)..."
docker pull python:3.12-slim

info "Saving preseed tars (loaded into the sandbox's private daemon at first boot)..."
docker image save python:3.12-slim -o "$PRESEED_DIR/python-3.12-slim.tar"
docker image save "$TESTS_TAG" -o "$PRESEED_DIR/maistro-engine-tests.tar"

info "Building the sbx template ($TEMPLATE_TAG)..."
docker build -f "$REPO_ROOT/deploy/sbx/template/Dockerfile" -t "$TEMPLATE_TAG" "$REPO_ROOT"

if [[ -n "${PUSH_TAG:-}" ]]; then
    docker tag "$TEMPLATE_TAG" "$PUSH_TAG"
    info "Pushing $PUSH_TAG..."
    docker push "$PUSH_TAG"
    info "Done. Reference '$PUSH_TAG' as the template in deploy/sbx/kit/spec.yaml."
elif command -v sbx >/dev/null 2>&1; then
    info "Loading template into sbx..."
    docker image save "$TEMPLATE_TAG" -o /tmp/maistro-sbx-template.tar
    sbx template load /tmp/maistro-sbx-template.tar
    rm -f /tmp/maistro-sbx-template.tar
    info "Done. Reference '$TEMPLATE_TAG' as the template in deploy/sbx/kit/spec.yaml."
else
    info "Built $TEMPLATE_TAG. Install sbx and run 'sbx template load', or re-run with PUSH_TAG=... to push."
fi
