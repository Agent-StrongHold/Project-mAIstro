---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# Issue 336 — reachable UI permissions

The permission-policy tests add four node IDs covering policy-source wiring,
least-privilege daily setup, task-scoped elevation, and the admin break-glass
role. Frontend behavior is validated by the TypeScript build and the matrix
script rather than a new browser-test inventory entry.

Validation evidence on the implementation head:

- `uv run pytest packages/hive-conductor/backend/tests/test_permission_policy.py packages/hive-conductor/backend/tests/test_api.py packages/hive-conductor/backend/tests/test_auth_middleware.py packages/hive-conductor/backend/tests/test_setup_guard.py -x -q` -> 98 passed, 1 skipped.
- `uv run pytest packages/hive-conductor/backend/tests/test_ws_auth.py packages/hive-conductor/backend/tests/test_providers_routes.py packages/hive-conductor/backend/tests/test_capabilities_routes.py -x -q` -> 22 passed, 6 skipped.
- `uv run python scripts/check-conductor-permission-matrix.py` -> 44 API entries and 31 UI mutations accepted.
- `npm --prefix packages/hive-conductor/frontend run build` -> TypeScript and Vite build passed.
- `uv run ruff check .` and `uv run ruff format --check .` -> passed.
