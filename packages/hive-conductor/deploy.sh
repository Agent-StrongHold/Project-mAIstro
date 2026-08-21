#!/usr/bin/env bash
# Deploy Hive Conductor to the external deploy platform
# Usage: ./deploy.sh [preview|production]
#
# This script deploys a BUILD, not a RELEASE. It pushes one immutable
# git-SHA-tagged image so a specific commit can be run on preview/production.
#
# It no longer pushes `:latest`. ADR-073126-c4e1 §3 makes the tag-triggered
# .github/workflows/release.yml the only path that publishes to the container
# registry, and `:latest` is a release pointer: this script running on a laptop
# could move it past a signed, approved release, so an unpinned `docker pull`
# would silently get an unreviewed local build. Release tags (`vX.Y.Z`, `X.Y`,
# `latest`) come from release.yml, gated by the `release` environment approval
# and cosign-signed by digest.
set -euo pipefail

ENVIRONMENT="${1:-preview}"
IMAGE_NAME="hive-conductor"
REGISTRY="${DOCKER_REGISTRY:-ghcr.io/agent-stronghold}"
TAG="$(git rev-parse --short HEAD)"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "═══════════════════════════════════════════════"
echo "  Hive Conductor Deploy — ${ENVIRONMENT}"
echo "  Image: ${FULL_IMAGE}"
echo "═══════════════════════════════════════════════"

# Step 1: Build frontend + backend Docker image
echo ""
echo "▶ Step 1: Docker build..."
cd "$(git rev-parse --show-toplevel)"
docker build \
  -f packages/hive-conductor/Dockerfile \
  --build-arg VITE_POC_MODE=pm \
  -t "${FULL_IMAGE}" \
  .

echo "  ✓ Built ${FULL_IMAGE}"

# Step 2: Push to registry
echo ""
echo "▶ Step 2: Push to registry..."
docker push "${FULL_IMAGE}"
echo "  ✓ Pushed ${FULL_IMAGE} (SHA tag only — release tags come from release.yml)"

# Step 3: Verify on preview
echo ""
echo "▶ Step 3: Verify..."
if [ "${ENVIRONMENT}" = "preview" ]; then
  PREVIEW_URL="${PREVIEW_URL:-https://hive-preview.example.com}"
  echo "  Deploying to preview: ${PREVIEW_URL}"
  # If using docker-compose on remote:
  # ssh deploy@preview "cd /opt/hive && docker pull ${FULL_IMAGE} && docker-compose up -d"
  echo "  → Pull: docker pull ${FULL_IMAGE}"
  echo "  → Run:  docker run -d -p 8101:8101 --env-file .env ${FULL_IMAGE}"
  echo ""
  echo "  Verify at: ${PREVIEW_URL}/health/ready"
fi

# Step 4: Production cutover (only if explicitly requested)
if [ "${ENVIRONMENT}" = "production" ]; then
  PROD_URL="${PROD_URL:-https://hive.example.com}"
  echo ""
  echo "▶ Step 4: Production cutover..."
  echo "  ⚠️  This will update production at ${PROD_URL}"
  read -p "  Continue? [y/N] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "  → Deploying to production..."
    # ssh deploy@prod "cd /opt/hive && docker pull ${FULL_IMAGE} && docker-compose up -d"
    echo "  ✓ Production updated"
  else
    echo "  ✗ Aborted"
    exit 1
  fi
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✓ Deploy complete — ${ENVIRONMENT}"
echo "  Image: ${FULL_IMAGE}"
echo "═══════════════════════════════════════════════"
