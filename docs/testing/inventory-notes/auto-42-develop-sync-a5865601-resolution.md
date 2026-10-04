---
inventory-delta:
  (none): all 14 suites match the recorded inventory unchanged
---

# auto-42 develop sync — resolve the preserved a58656017 merge conflict

The previous round left the develop sync mid-merge at HEAD `5f302247a` with
exactly one unmerged path. This round resolved it and committed the merge as
`def7f9503` (MERGE_HEAD `a58656017`, develop's M4-B1 knowledge-stage ladder,
ADR-103 / SPEC-100426).

## What the conflict resolution did

- `tests/migrations/test_capability_invocation_effect_index_migration.py`
  ("deleted by us"): kept the lane's deletion, re-applying the standing
  reconciliation (`auto-42-develop-sync-55be1459-reconciliation.md`, round 15).
  Develop's 20-line edit only bumps the chain-tip walk `051` → `052` inside a
  conformance test for `043_capability_invocation_effect_index` — a migration
  this lane retired as a competing mechanism. The #1194/#42 effect-claim shape
  lives in migration `035` (`effect_scope` +
  `uq_capability_invocation_active_effect`, amended in place) with the same
  shape in `PgInvocationStore.ensure_schema`; live-catalog coverage is
  `test_migration_chain.py`'s re-application test (stamp
  `039_quota_usage_event_identity`, re-upgrade, assert `effect_scope` and the
  scope-keyed claim index survive adoption). Keeping develop's edit would test
  a migration that does not exist on this branch.
- Everything else auto-merged: `052_learning_stage_ladder` chains onto `051`
  (single linear head — `alembic heads` = `052 (head)`); the merged
  `test_migration_chain.py` carries both our `effect_scope` re-application
  insert and develop's `learning_stage_transitions` expectation; develop's
  tests arrived with develop's own delta notes (`auto-117-knowledge-stage-ladder`).
- Quality ledgers: no rows lost by the merge (numstat both parents → result).
  Where both parents rewrote the same row the merge kept this lane's side,
  matching this branch's code: `radon-baseline.json` complexity 11 with the
  `_resolve_provider` extraction rationale, and `shipped-surface-truth.json`'s
  `RunStore.claim_run_by_effect` wording. Develop's
  `durable-table-retention.json` additions for `learning_stage_transitions`
  were adopted (`check-durable-table-inventory.py`: 89 tables, each with a
  declared retention).

## Inventory

No recorded suite count moved: `check-suite-inventory.py` reports all 14
suites matching the recorded inventory at the merged head (core 12774,
tests/ 4293, canvas 519, server 501, …), with zero duplicate or
byte-identical test identities across 25147 collected node IDs. The merge's
new tests are covered by develop's own recorded deltas.

## Executed evidence (at merged head def7f9503)

- `uv sync --locked --all-extras` (CI quality job setup); `uv run ruff check .`
  and `ruff format --check .` — clean (2878 files).
- `scripts/check-vulture-baseline.py` (CI args) — 1342/1342 identities, rc=0.
- `scripts/check-radon-baseline.py` — 143/143 blocks, rc=0 (merged ledger
  matches merged scan).
- `check-reachability.py`, `check-reachability-dispositions.py`,
  `check-durable-table-inventory.py` (89 tables), `check-promotion-surface.py`,
  `check-backlog-consistency.py` — all rc=0.
- `check-suite-inventory.py` — all 14 suites match.
- `mypy --strict packages/maistro-core/src` — Success, 700 files (under the
  `--extra dev`-only sync the only errors are the 5 documented
  `maistro_bootstrap` import-not-found traps; clean under `--all-extras`).
- Live PostgreSQL 18 (throwaway `pgvector/pgvector:pg18` on :55444):
  `alembic upgrade head` → `downgrade base` → `upgrade head` — clean chain
  walk including the new `052`; `tests/migrations` — 101 passed (98 prior +
  3 develop ladder tests); `tests/migrations` leaves the database empty, so
  the schema was re-migrated before the DSN-gated suites below.
- `packages/maistro-core/tests/memory/learnings` + `tests/persistence`
  against the migrated PG18: 903 passed, 0 skipped (includes develop's
  `test_pg_learning_stage`, `test_learning_lifecycle`,
  `test_stage_grants_no_authority`, `test_sqlite_learning_stage`).
- `tests/graph/durable_runs` on live PG: 624 passed, 0 skipped.
- `tests/capabilities` + `tests/a2a` + `tests/runs` on live PG:
  1920 passed, 3 skipped.
- Driver's 16-path targeted battery with both DSNs set: 696 passed, 0 skipped
  (the 124 PG-gated legs that skip without a server all ran and passed).
- The pyright prior finding stays fixed: `InvocationStore.list_effect`'s
  Protocol stub ends in the elided `...` body (commit `5f302247a`), zero
  diagnostics in `invocation.py` per that commit's analyzer run; runtime
  dispatch never executes Protocol stub bodies.
