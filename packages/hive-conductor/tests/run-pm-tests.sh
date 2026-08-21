#!/usr/bin/env bash
# Run the PM workflow API tests against a local hive-conductor instance.
# Usage:
#   ./tests/run-pm-tests.sh              # assumes localhost:8101
#   ./tests/run-pm-tests.sh http://host:port
set -euo pipefail

BASE_URL="${1:-http://localhost:8101}"
echo "🐝 Testing PM workflow against $BASE_URL"

# Wait for health
echo "⏳ Waiting for hive to be ready..."
for i in $(seq 1 30); do
  if curl -fsS "$BASE_URL/health/ready" >/dev/null 2>&1; then
    echo "✅ Hive is ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "❌ Hive not ready after 60s"
    exit 1
  fi
  sleep 2
done

# Run pytest
export HIVE_BASE_URL="$BASE_URL"
cd "$(dirname "$0")/.."
python3 -m pytest tests/e2e/test_pm_workflow_api.py -v --tb=short "$@"
