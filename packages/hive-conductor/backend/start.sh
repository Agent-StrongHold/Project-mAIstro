#!/bin/bash
# Source credentials from the repo root .env, if present
ROOT_ENV="$(git rev-parse --show-toplevel 2>/dev/null)/.env"
if [ -f "$ROOT_ENV" ]; then
  export $(grep -E "^[A-Z]" "$ROOT_ENV" | xargs)
elif [ -f "../../../../../.env" ]; then
  export $(grep -E "^[A-Z]" "../../../../../.env" | xargs)
fi
exec uvicorn main:app --host 0.0.0.0 --port 8101
