---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# #389 develop-sync merge: cover the scan-budget guard the reformat exposed

Resolving the origin/develop sync for the #389 branch (merge `ca815c5a2`)
required reformatting three files develop itself ships unformatted under the
pinned ruff 0.15.12 (`ruff format --check` fails on pure `origin/develop` for
the same three files). Two of them are under the diff-coverage gate's measured
roots, so their reformatted lines entered the "lines this candidate touched"
net (`scripts/check-diff-coverage.py coverage.xml --base origin/develop`):

- `packages/hive-conductor/backend/routes/audit.py` — one reformatted line,
  already covered by `test_audit_routes.py` (file at 100%).
- `packages/hive-conductor/backend/services/agent_materialization.py` — one
  reformatted line: the `MAX_SCAN_TEXT` guard inside `scan_messages`
  (`ScanBudgetExceeded` for a user turn over 64 KiB). **No test executed it**:
  every other `ScanBudgetExceeded` test raises the exception from a stub
  (`test_agents_routes.py`, `test_chat_created_agents.py`, `test_chat_voice_gates.py`),
  so the guard itself had never run anywhere in the suite.

## Test delta (+1, in `packages/hive-conductor/backend/tests`)

`test_agent_materialization.py::test_scan_messages_refuses_an_oversized_user_turn_before_the_model`
drives the real `scan_messages` with a `MAX_SCAN_TEXT + 1` character user turn
and asserts the refusal names the offending turn index. This is not
format-chasing: it closes a real coverage hole on a fail-closed seam (an
oversized turn must be refused before the model sees it), which the diff gate
only exposed because the reformat dragged the line into the scored diff.

## Gate evidence on the merged head (merge `ca815c5a2`, base `f5fa43771`)

- `check-vulture-baseline.py` (exact-debt-ledger), `RATCHET_BASE_REV=origin/develop`
  → exit 0: 1359 reviewed identities → 1359 findings (base/candidate resolve
  exactly as the merge queue's synthetic merge will).
- `check-diff-coverage.py coverage.xml --base origin/develop` → exit 0 after
  this test: 15 changed files measured, all ≥ 90% lines / ≥ 80% branches.
- `check-api-route-contracts.py` → OK (279 handlers, 15 audited, 0 canned).
- six-file #389 backend battery → 197 passed; `tests/test_check_api_route_contracts.py`
  → 31 passed; `packages/maistro-core/tests/graph/durable_runs` → 563 passed,
  39 skipped (PG-less env).
- ruff check / ruff format --check → clean (3 develop-side files reformatted
  as part of the merge resolution).
