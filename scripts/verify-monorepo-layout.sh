#!/usr/bin/env bash
# Fail if expected monorepo paths are missing (CI / local sanity).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

missing=0
need() {
  if [[ ! -e "$1" ]]; then
    echo "missing: $1" >&2
    missing=1
  fi
}

need packages/maistro-core/pyproject.toml
need packages/maistro-server/pyproject.toml
need packages/maistro-turing/pyproject.toml
need packages/maistro-canvas/pyproject.toml
need packages/maistro-bootstrap/pyproject.toml
need packages/maistro-registry/pyproject.toml
need packages/maistro-evolve/pyproject.toml
need packages/hive-conductor/frontend/package.json
need packages/hive-conductor/backend/requirements.txt
need docs/specs/README.md
need pyproject.toml

if [[ "$missing" -ne 0 ]]; then
  exit 1
fi
echo "ok: monorepo layout"

# TEMPORARY formatting probe for PR #658. This commit is reverted after CI prints
# Ruff's exact formatter delta; no probe code is intended to merge.
echo "::group::PR #658 exact Ruff formatting probe"
uv run ruff format \
  scripts/check-enumerations-provenance.py \
  scripts/check-model-egress.py \
  scripts/check-reachability-dispositions-provenance.py \
  scripts/check-reachability-provenance.py \
  scripts/check-vulture-baseline.py \
  scripts/check_mutation_baseline.py \
  tests/test_check_ratchet_provenance.py
git diff -- \
  scripts/check-enumerations-provenance.py \
  scripts/check-model-egress.py \
  scripts/check-reachability-dispositions-provenance.py \
  scripts/check-reachability-provenance.py \
  scripts/check-vulture-baseline.py \
  scripts/check_mutation_baseline.py \
  tests/test_check_ratchet_provenance.py
echo "::endgroup::"
