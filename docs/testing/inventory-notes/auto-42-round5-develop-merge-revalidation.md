---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 round 5: develop-merge re-validation at 852f104d58c0 (live-PG race proof)

Re-verification of the incoming head
`852f104d58c0b68c7b09b62da41d4dc2eabf9088` (merge of develop
`0c8370a8eaa4cd061e6b8c71524e28b746325684` into auto-42). The prior
round-4 note claims were re-derived from scratch; no product or test
code needed changing this round — delta is this evidence record only.

## Prior findings, re-checked at the new head

1. **Durable effect claim race** — fix confirmed in-tree at all three
   surfaces (`invocation_store.py` `_CLAIM_DDL`, `pg_invocation_store.py`
   `_CLAIM_DDL`, `alembic/versions/035_capability_invocations.py`):
   partial unique index `uq_capability_invocation_active_effect` on
   `(run_id, effect_scope, binding_id, effect_key)` over every non-FAILED
   status with legacy backfill. NEW this round: reproduced the original
   failure mode against **live PostgreSQL** (pgvector/pg18 container,
   fresh DB migrated `alembic upgrade head` to single head 044): two
   separate connections claiming one stable
   `effect_scope` from different NodeRun/Attempt identities raced 20
   rounds -> round 0: 1 success + 1 `UnsafeEffectRetry`, all later
   rounds refused, **exactly 1 persisted row**. The prior
   "dispatches=2" double-dispatch is now impossible on PG, not only on
   the fake-pool suite. `DATABASE_URL=... alembic upgrade head` on the
   fresh DB ran clean and `pg_indexes` shows the real scope-keyed index.
2. **Vulture gate** — `uv run python scripts/check-vulture-baseline.py`
   exits **1** at this head (a2a.py `create_a2a_task` debt is gone, the
   round-3/4 repair holds), but with candidate-ledger churn. Established
   this is **inherited from the develop base, not introduced by the
   branch**: `git archive 0c8370a8e` scanned with the identical pinned
   vulture 2.16 yields the **identical 1434-finding multiset**
   (`comm` of stable keys: zero added, zero removed), identical ledger,
   identical script and `ratchet-authorizations.json`. Per the gate's own
   contract the residual requires a separately landed reviewed grant
   (`--update` in a candidate cannot authorize it), so it is a
   repo-level quality-infra item affecting develop equally. Minor
   branch-attributable piece: a2a test coverage made
   `a2a/delegate.py`/`guest_peers.py`/`lifecycle.py` identities used, so
   their stale ledger rows want pruning by the integrator's next ledger
   pass.
3. **#1194 still OPEN** (`gh issue view`, read-only): #1169 CLOSED,
   #1170 CLOSED, **#1194 OPEN**. Still the sole acceptance residual;
   closure is an orchestrator action outside this lane's authority.

## Validation battery at 852f104d58c0 (all green unless noted)

- Driver logs (job 44e74e68): `uv sync --locked --extra dev`,
  `ruff check .` ("All checks passed!"), `ruff format --check .`,
  suite inventories core+server — all pass; the driver's pytest
  selection: 159 passed.
- `uv run mypy <six package srcs>` -> "Success: no issues found in 725
  source files".
- SQLite legs: `runs` 977 passed / 226 skipped; `tasks` +
  `graph/durable_runs` + `capabilities` invocation suites green;
  `tests/runtime` 22 passed (cancellation propagation, deadline vs a
  cancellation-swallowing provider, distinct deadline classification);
  `test_ambiguous_effect_replay_guard.py` +
  `test_attempt_execution.py` + `test_chat_attempt_recovery.py` -> 41
  passed (incl. `test_a_second_execution_adds_an_attempt_rather_than_a_node_run`).
- Live-PG legs (`MAISTRO_TEST_PG_DSN` on pgvector/pg18):
  `runs` **1200 passed / 3 skipped**; `tasks` + `graph/durable_runs` +
  `capabilities` invocation suites **989 passed** (lease/fence/reclaim,
  chat terminal-write recovery, PG store conformance all executed on
  the real backend).
- Gates: `check-execution-lifecycles.py` -> 19/19 classified, exit 0
  (no physical-execution bypass); `check-durable-table-inventory.py` ->
  69 tables ok; `alembic heads` -> single head 044.
- PR 1326 body and branch commit messages contain no premature
  fixes/closes/resolves keywords.

## Acceptance state at this head

In-tree acceptance for #42 remains fully test-proven at the new head,
now with a live-PostgreSQL race reproduction for the effect-claim
contract. Sole residual, unchanged: #1194 is OPEN while #42's text
requires #1169/#1170/#1194 closed before completion — handoff to the
integrator; no code repair is available or needed in this lane.
