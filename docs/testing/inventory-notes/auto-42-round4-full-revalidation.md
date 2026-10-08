---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 repair round 4: full re-validation at 8da9e2db6eef (incl. PG legs)

The round started from the previous round's block: the repair worker made no
commit and emitted no result line — a clean tree at the incoming head was
"not proof of repair". This round therefore re-derived every claim from
scratch against reachable production behavior and meaningful tests at head
`8da9e2db6eef5e5b3740c7022220894c5354695f`. No product or test code needed
changing: the effect-scope claim fix (`e55917ab7`) and the A2A vulture
repair (`1054aae4b`) are already committed on the branch, so this round's
delta is this evidence record only.

## Prior findings, re-checked

1. **Durable effect claim keyed `node_run_id` instead of the stable logical
   effect** (`invocation_store.py`, `pg_invocation_store.py`, alembic 035)
   — FIXED in-tree. All three schema surfaces key the partial unique index
   `uq_capability_invocation_active_effect` on
   `(run_id, effect_scope, binding_id, effect_key)` over every non-FAILED
   status, with a legacy `effect_scope = node_run_id` backfill. Regression
   tests pin the exact prior failure mode —
   `test_invocation_store.py::test_sqlite_store_rejects_cross_node_run_active_effect_claim`
   and `::test_sqlite_service_deduplicates_logical_effect_across_node_run_visits`
   (asserts `calls == 1` across two NodeRun visits of one stable effect —
   the prior "dispatches=2" repro), plus the PG twins in
   `test_pg_invocation_store.py`. Alembic `035_capability_invocations.py`
   was exercised for real: `DATABASE_URL=... uv run alembic upgrade head`
   ran the whole chain (… -> 044) cleanly on a fresh pgvector/pg18.
2. **Vulture gate exit 1 on `a2a.py create_a2a_task`** — FIXED via
   `1054aae4b` (scanner-reference tuple, ledger row pruned, stale branch
   grant dropped). Exact CI invocation re-run this round: exit 0,
   1403 reviewed identities -> 1403 findings, unclassified 0, baseline
   `341c900b0bca` -> candidate `8da9e2db6eef`.
3. **#1194 still OPEN** — re-checked read-only via `gh issue view`: #1169
   CLOSED, #1170 CLOSED, **#1194 OPEN**. Its in-tree mechanics exist
   (`graph/nodes/base.py` `ReplaySemantics`, `compliance_block` penalty
   keyed by `logical_effect_key`, `agent_delegate_remote` EFFECT_KEY with
   request-borne idempotency keys, `tests/tasks/test_idempotency*.py`
   conformance suites), but closing the GitHub issue is an orchestrator
   action outside this lane's authority (no GitHub mutations). This remains
   the sole acceptance residual for #42.
4. **No commit from the previous worker** — this note and its commit are
   this round's proof-of-work.

## Validation battery at 8da9e2db6eef (all green)

- `uv run ruff check .` -> "All checks passed!"; `uv run ruff format
  --check .` -> "2602 files already formatted".
- `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src` ->
  "Success: no issues found in 725 source files".
- Exact CI vulture invocation (above) -> exit 0.
- SQLite legs: `runs` 964 passed / 226 skipped, `tasks` 349 passed /
  14 skipped, `capabilities` + `runtime` + `test_a2a_api.py` green —
  matching round 3.
- **PG legs executed for the first time this lane** against a migrated
  pgvector/pg18 (`MAISTRO_TEST_PG_DSN` set after `alembic upgrade head`;
  the earlier 4 failures + 662 errors in this configuration were solely the
  unmigrated-database environment, and disappeared once migrated):
  `runs` + `tasks` -> **1550 passed, 3 skipped**; `runs` alone ->
  1187 passed / 3 conditional skips (payload-move and continuation-store
  parametrizations, not environment); `capabilities` + `runtime` +
  `test_a2a_api.py` -> 369 passed. This promotes the durable lease/fence/
  reclaim, chat-attempt-recovery and PG store conformance evidence from
  "skipped locally" to executed.
- Gates: `check-durable-table-inventory.py` -> 69 tables ok;
  `check-execution-lifecycles.py` -> 19/19 classified, 0 violations;
  `check-merge-markers.py` -> ok; `check-suite-inventory.py` -> 14/14
  match.

## Acceptance state at this head

Every in-tree acceptance criterion of #42 is test-proven at this head
(Attempt-per-execution, chronological retry Attempts, one canonical
idempotency/effect contract across memory/SQLite/PostgreSQL, runtime
cancellation/deadline classification, chat lease/fence/terminal-write
recovery, correlated Run/NodeRun/Attempt/Invocation/Events persistence,
no physical-execution bypass per the lifecycle gate). The single residual
is administrative: #1194 remains OPEN on GitHub and #42's own text requires
its closure before completion — handoff item for the integrator, not a
code defect this lane can repair.
