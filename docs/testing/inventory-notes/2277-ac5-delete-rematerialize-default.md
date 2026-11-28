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

## CI repair (2026-11-28, head 20a57105d628): invented marker broke the AC-state ratchet

CI at this head failed exactly one check, `Quality / Acceptance state`; the
`Quality gate (Pillars 1–4, 7, 8)` failure was its dependency cascade. Cause:
the pin test carried `@pytest.mark.ac("#2277/AC-5")`, an id no spec/ADR
declares (`#2277` has no AC corpus entry), so `markers_without_criterion`
rose 2 → 3 above its ceiling. Reproduced locally with CI-exact arguments:

- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  547eb70afd64...` → `FAIL: the repository moved away from its recorded
  state — markers_without_criterion: 3 exceeds the ceiling of 2`.
- Fix: dropped the invented decorator; the test keeps
  `ADR-092326-7ed7/AC-1` (declared; one stable Workspace Agent per
  Workspace — the test asserts the successor's resolved id is stable and
  differs from the predecessor's), and the docstring keeps the #2277/AC-5
  linkage. Test count unchanged; inventory delta above still holds.
- Same command after the fix → exit 0: `markers naming no criterion: 2`,
  ratchet/meter/mandate/chain all `OK`.
- Re-validation at the fix: targeted identity+routes suites 26 passed;
  red-check re-proven (materialization default `program_manager` →
  `pm_fleet` fails exactly
  `test_after_delete_and_re_materialization_the_default_persona_returns`;
  reverted, 0-diff); full backend suite 4739 passed / 38 skipped (Postgres
  backed); `ruff check .` + `ruff format --check .` clean;
  `check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
  ok; vulture CI-exact args exit 0 (1217 = 1217); the six parity/truth
  gates above re-run, all exit 0.
