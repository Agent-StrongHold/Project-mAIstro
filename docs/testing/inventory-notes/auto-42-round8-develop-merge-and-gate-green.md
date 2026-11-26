---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 round 8: repair lane — develop sync merge + full gate revalidation at b3f3c864f

The round-7 verification was rejected for a process reason only
("verification worktree changed; evidence rejected | head moved
fa10be9086 -> b6ddd1bd1e" — the delta was one evidence-note commit). This
repair round resolves the lane's standard sync obligation and re-proves
every gate at the new head. No production code was changed by this round;
the only merge-introduced delta is develop's own WIP
(`73060a7ee` capability admission governance, `b43175c1d` task identity
provenance) plus this and prior evidence notes.

## Develop sync resolution

- `git merge --no-ff origin/develop` at b6ddd1bd1 merged cleanly (no
  conflicts) -> merge commit `b3f3c864f`. Branch now 34 ahead of
  origin/develop, 0 behind.
- Migration chain integrity on real PostgreSQL: scratch DB on container
  `auto-42-pg5`, `DATABASE_URL=… uv run alembic upgrade head` ran the
  full linearized chain (including develop's `041_task_identity_provenance`
  -> `042_task_receipt_dispatch_inputs` lineage rejoined with this
  branch's `042` -> `039_quota_usage_event_identity` lineage) to a single
  head `044`; `uv run alembic heads` = `044 (head)` in the tree.
  Scratch DB dropped afterwards.

## Gates re-executed at b3f3c864f (all green)

- `uv run ruff check .` — "All checks passed!"; `ruff format --check .` —
  2609 files already formatted.
- Lane pytest selection (a2a guests, invocation stores, durable_runs,
  graph nodes, sqlite runs store, server A2A API, `test_migration_chain`):
  **161 passed, 12 skipped**.
- `tests/tasks/test_attempt_execution.py` + `tests/runtime` +
  `tests/runs/test_chat_attempt_recovery.py`: **63 passed**.
- `tests/graph/durable_runs` + `tests/runs`: **1537 passed, 265 skipped**.
- `tests/capabilities` + `tests/a2a` + server A2A API (develop's changed
  admission surface): **505 passed**.
- **Live-PG runs leg**: `MAISTRO_TEST_PG_DSN=… pytest tests/runs -q` ->
  **1200 passed, 3 skipped** (matches round 7 at the new head).
- **Live-PG durable_runs/tasks/runtime leg**: **649 passed**.
- `scripts/check-execution-lifecycles.py`: exit 0, 19/19 classified
  (3 CANONICAL / 8 CONVERGE / 6 DOMAIN / 2 PROJECTION), ratchet vs the
  new base b43175c1d.
- `scripts/check-suite-inventory.py` core (11472) + server (415): ok.
- `uv run mypy` on all six package srcs: "Success: no issues found in
  726 source files".

## Vulture exact-debt ledger: CI-repair round executed, no amendment needed

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` at b3f3c864f: **exit 0**
  — 1402 reviewed identities, 1402 findings, `unclassified: 0`,
  `never_allowlist: 0`. The round-6/7 develop-inherited ledger churn is
  resolved by develop's own `quality/vulture-baseline.json` state carried
  in through the merge; this branch still adds zero unbanked identities.
  No identity was eliminated by this round, so no ledger amendment was
  made (gate is green; amendment would be gratuitous).

## Effect-race proof re-executed live at the merged head

Two-process-style concurrent proof (repair-lane script, scratch DB, head
044): two concurrent `InvocationExecutionService` contestants with
different NodeRun/Attempt identities (`nr-1/at-1` vs `nr-2/at-2`) claim
stable scope `run-race:charge:42` -> `DISPATCHES ['dispatch']` (exactly
one physical provider call), loser raises `UnsafeEffectRetry`, exactly
**1 persisted row** (first-visit identities `nr-1/at-1`, status
`completed`, `effect_scope 'run-race:charge:42'`). Bonus evidence from
the same scratch DB: a completed invocation persisted by an earlier
*process* was returned to a later fresh process via the scoped history
read with **zero** re-dispatch (cross-process dedup on real PG).
Regression tests
`test_pg_invocation_store_rejects_cross_node_run_active_effect_claim` and
`test_pg_service_deduplicates_logical_effect_across_node_run_visits`
pass at this head. The store/migration effect-scope code is
byte-identical to the round-7 verified state (`git diff fa10be9086..HEAD`
empty for `invocation_store.py`, `pg_invocation_store.py`,
`035_capability_invocations.py`).

## Residuals (unchanged, orchestrator-owned)

- Live `gh` (read-only): #1169 CLOSED, #1170 CLOSED, **#1194 OPEN**.
  #42's acceptance requires all three closed; closing #1194 is a GitHub
  mutation this lane is prohibited from performing. No code repair for
  this exists in this lane — the replay/idempotency contract #1194 asks
  for is implemented and enforced (see above); only the issue-state
  action remains for the orchestrator.
- No premature-closure exposure checked: merge commit messages on this
  branch reference #42 by title only ("(#42)" trailers in commit
  subjects, no "Fixes/Closes #42" keyword lines in bodies of this
  round's commits).
