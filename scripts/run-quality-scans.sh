#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHONPATH_ENTRIES=(
  "$ROOT/.venv/lib/python3.13/site-packages"
  "$ROOT/packages/maistro-core/src"
  "$ROOT/packages/maistro-server/src"
  "$ROOT/packages/maistro-turing/src"
  "$ROOT/packages/maistro-canvas/src"
  "$ROOT/packages/maistro-design/src"
  "$ROOT/packages/maistro-bootstrap/src"
  "$ROOT/packages/maistro-rsi/src"
  "$ROOT/packages/maistro-evolve/src"
  "$ROOT/packages/maistro-registry/src"
  "$ROOT"
)
export PYTHONPATH="$(IFS=:; echo "${PYTHONPATH_ENTRIES[*]}")${PYTHONPATH:+:$PYTHONPATH}"

run_python_module_or_bin() {
  local module="$1"
  local bin="$2"
  shift 2
  if uv run python -c "import ${module}" >/dev/null 2>&1; then
    uv run python -m "$module" "$@"
  else
    "$bin" "$@"
  fi
}

run_optional_module_or_bin() {
  local module="$1"
  local bin="$2"
  shift 2
  local status=0
  if uv run python -c "import ${module}" >/dev/null 2>&1; then
    uv run python -m "$module" "$@" || status=$?
  elif command -v "$bin" >/dev/null 2>&1; then
    "$bin" "$@" || status=$?
  else
    echo "WARN: ${bin} is not installed; skipping ${bin} scan" >&2
    return 0
  fi

  if [[ "$status" -ne 0 ]]; then
    echo "WARN: ${bin} reported findings/status ${status}; treating optional scanner as advisory" >&2
  fi
}

ruff check .
run_python_module_or_bin pytest pytest -q --import-mode=importlib
run_python_module_or_bin mypy mypy \
  packages/maistro-core/src \
  packages/maistro-server/src \
  packages/maistro-turing/src \
  packages/maistro-canvas/src \
  packages/maistro-bootstrap/src \
  packages/maistro-registry/src
run_optional_module_or_bin radon radon cc packages tests -s -n C -e "*/.venv/*"
if uv run python -c "import vulture" >/dev/null 2>&1; then
  uv run python scripts/check-vulture-baseline.py packages tests --exclude "*/.venv/*" || {
    status=$?
    echo "WARN: vulture baseline reported findings/status ${status}; treating optional scanner as advisory" >&2
  }
elif command -v vulture >/dev/null 2>&1; then
  python scripts/check-vulture-baseline.py packages tests --exclude "*/.venv/*" || {
    status=$?
    echo "WARN: vulture baseline reported findings/status ${status}; treating optional scanner as advisory" >&2
  }
else
  echo "WARN: vulture is not installed; skipping vulture scan" >&2
fi
