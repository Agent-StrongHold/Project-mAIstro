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

# The template and nested test image are DISTRIBUTED surfaces too. Do not let
# this operator-only build path be the one image path with no license evidence.
# CI's four-image job cannot build the sandbox because Docker Sandboxes creates
# the preseed daemon during this script, so the producer owns this scan. It runs
# before an optional push so a missing license cannot publish an unreviewed tag.
command -v syft >/dev/null 2>&1 || {
    echo "syft 1.49.0 is required to produce the sbx license inventory" >&2
    exit 1
}
syft version | grep -F '1.49.0' >/dev/null || {
    echo "syft 1.49.0 is required; refusing an unpinned license inventory" >&2
    exit 1
}
LICENSE_OUTPUT_DIR="${LICENSE_OUTPUT_DIR:-$REPO_ROOT/deploy/sbx/license-inventory}"
mkdir -p "$LICENSE_OUTPUT_DIR/sboms"
syft "$TEMPLATE_TAG" -o cyclonedx-json > "$LICENSE_OUTPUT_DIR/sboms/sbx-template.json"
syft "$TESTS_TAG" -o cyclonedx-json > "$LICENSE_OUTPUT_DIR/sboms/sbx-tests.json"
python3 "$REPO_ROOT/scripts/check-license-inventory.py" \
    --policy "$REPO_ROOT/quality/license-policy.json" \
    --only sbx-template \
    --only sbx-tests \
    --sbom "sbx-template=$LICENSE_OUTPUT_DIR/sboms/sbx-template.json" \
    --sbom "sbx-tests=$LICENSE_OUTPUT_DIR/sboms/sbx-tests.json" \
    --artifact "sbx-template=$TEMPLATE_TAG" \
    --artifact "sbx-tests=$TESTS_TAG" \
    --output "$LICENSE_OUTPUT_DIR/license-inventory.json"
info "License inventory: $LICENSE_OUTPUT_DIR/license-inventory.json"

# Vulnerability scanning, same policy as CI's containers job (#346). CI
# cannot build these images (the preseed daemon constraint recorded in
# quality/image-inventory.json), so the producer owns this gate too: a
# HIGH/CRITICAL trivy finding or a grype high-with-fix finding stops the
# script BEFORE the push below, so a vulnerable image cannot leave the
# build host. The tools are required on PATH at exactly the versions CI
# pins (security.yml: trivy v0.73.0, grype v0.116.0) — the same fail-closed
# pinned-tool contract as the syft license gate above: an unpinned or
# missing scanner is a refusal, not a skip.
TRIVY_VERSION="0.73.0"
GRYPE_VERSION="0.116.0"
command -v trivy >/dev/null 2>&1 || {
    echo "trivy $TRIVY_VERSION is required to vulnerability-scan the sbx images" >&2
    exit 1
}
trivy --version | grep -F "$TRIVY_VERSION" >/dev/null || {
    echo "trivy $TRIVY_VERSION is required; refusing an unpinned vulnerability scan" >&2
    exit 1
}
command -v grype >/dev/null 2>&1 || {
    echo "grype $GRYPE_VERSION is required to vulnerability-scan the sbx images" >&2
    exit 1
}
grype version | grep -F "$GRYPE_VERSION" >/dev/null || {
    echo "grype $GRYPE_VERSION is required; refusing an unpinned vulnerability scan" >&2
    exit 1
}
for image in "$TEMPLATE_TAG" "$TESTS_TAG"; do
    info "trivy ${image} (HIGH/CRITICAL, ignore-unfixed)"
    trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed \
        --ignore "$REPO_ROOT/.trivyignore.yaml" "$image"
    info "grype ${image} (high with fix available)"
    grype "$image" --fail-on high --only-fixed --output table
done

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
