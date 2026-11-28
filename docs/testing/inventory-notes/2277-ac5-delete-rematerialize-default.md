---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# 2277 AC-5 delete + re-materialize default

Focused re-validation of merged #2277 / PR #2292: pin the AC-5 flow — after a
Workspace delete (whose cascade removes the Workspace Agent row outright) and a
later re-materialization for a successor Workspace, the fresh Agent row is born
with the default `program_manager` persona, a swapped persona never ghosts onto
the successor, and the successor swaps like any other.

## packages/hive-conductor/backend/tests: +1

- `test_workspace_agent_identity.py` (+1)
  `test_after_delete_and_re_materialization_the_default_persona_returns`:
  resolve → swap to `delivery` → delete workspace (row gone) → new Workspace
  resolves a fresh row (`program_manager`, different id) → swap again holds.
  Red-checked: mutating the fresh-materialization default makes the test fail.

## Local re-validation evidence (2026-11-28, head 8432a338f2ac)

- `uv run pytest test_workspace_agent_identity.py test_workspace_agent_persona_routes.py -q`
  → 26 passed.
- Red-check reproduced: swapping the materialization default
  (`DEFAULT_PERSONA_TEMPLATE_ID` → `pm_fleet` at the insert site) fails exactly
  this test; revert restored a 0-diff tree.
- `uv run pytest packages/hive-conductor/backend/tests -q` → 4657 passed,
  120 skipped (service-backed), 0 failed.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run python scripts/check-suite-inventory.py` → ok (this note's +1 delta
  reconciles the suite).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1217 = 1217).
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.

## Independent re-validation (2026-11-28, head 561bfba207ef, post develop-sync)

- Worktree re-synced (`uv sync --locked --extra dev`) before any gate.
- `uv run pytest tests/test_workspace_agent_identity.py
  tests/test_workspace_agent_persona_routes.py -q` → 26 passed.
- Red-check reproduced independently at this head: mutating
  `DEFAULT_PERSONA_TEMPLATE_ID` (`program_manager` → `pm_fleet` in
  `services/workspace_agent.py`) fails exactly
  `test_after_delete_and_re_materialization_the_default_persona_returns`;
  reverted by hand, `git status` clean (0-diff).
- `uv run pytest tests -q` (full hive backend suite) → 4657 passed,
  120 skipped (service-backed), 0 failed.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run python scripts/check-suite-inventory.py` → ok (21 suites match).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1217 = 1217).
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
- UI/API parity gates: `check-frontend-api-routes` (177 frontend call sites
  resolve to 262 registered routes), `check-frontend-typed-client`,
  `check-api-route-contracts`, `check-route-permissions`,
  `check-public-routes` → all exit 0, none new.
