#!/usr/bin/env bash
# Start Hive backend for PM Fleet POC (loads repo-root .env).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/packages/hive-conductor/backend"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT/.env"
  set +a
fi

export MAISTRO_POC_MODE="${MAISTRO_POC_MODE:-pm}"
export HIVE_POC_MODE="${HIVE_POC_MODE:-pm}"
export PYTHONPATH="$ROOT/packages/maistro-core/src:."

UVICORN="${ROOT}/.venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  UVICORN="uvicorn"
fi

echo "PM POC: MAISTRO_POC_MODE=$MAISTRO_POC_MODE HIVE_POC_MODE=$HIVE_POC_MODE"
echo "Hive API: http://127.0.0.1:8101  (health: /health pm_poc_mode)"
exec "$UVICORN" main:app --host 127.0.0.1 --port 8101 --reload
