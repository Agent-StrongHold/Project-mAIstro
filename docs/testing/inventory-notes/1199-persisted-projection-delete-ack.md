---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# #1199: persisted projection restart and truthful DELETE acknowledgment

Scope snapshot: issue #1199 only, starting at
`5d678894602e2612cea34e56b982c63a5fb52ef7`, base
`9c02cfd7d1787a29eec9f2443c3b9ed2e9869979`. Process the existing
scheduler/store acceptance tests, relevant ADRs, and the explicitly authorized
vulture gate; no GitHub mutations or unrelated ledger edits.

The prior driver's failure was pytest on
`packages/maistro-core/tests/conftest.py` (exit 5, no tests collected), not
scheduler behavior. The exact vulture scan passes unchanged: 1221 reviewed
identities / 1221 findings, so no ledger amendment is justified.

## Repair and regression

`DELETE /v1/schedules/{id}` committed canonical deletion and its tombstone,
then leaked an opaque error if durable Hive projection removal failed.
The new test failed before the fix with `RuntimeError: Hive persistence
delete unavailable` at `routes/schedules.py:467`. DELETE now reports explicit
503 degraded acknowledgment naming the schedule and persisted deletion,
matching UPDATE's existing post-commit semantics. It never rolls back
canonical truth or re-arms recurrence.

One new test function, parametrized over memory/SQLite/PostgreSQL, adds three
items. It fails the real PersistedStore delete after canonical commit,
checks the response and tombstone, reopens both databases, verifies startup
retires the stale persisted Hive row without selecting future work, then
reopens Hive again to prove repair is durable.

Existing projection-authority tests now use real file-backed
State/PersistedStore/ModelStore rather than only a process-local dict.
Their crash-restart helper reopens the Hive database as well as canonical
SQL state. The edit regression also checks template identity alongside
enabled/cron/timezone. Legacy test inserts now use acknowledged store writes.
The UPDATE-outage test uses a scoped monkeypatch context so it does not undo
its entire configured authority fixture mid-test.

## Architecture and limits

Accepted ADR-082126-f69c supersedes ADR-046: recurrence produces canonical
Runs, not APScheduler jobs or Task lifecycles. ADR-082426-82c7 retains the
occurrence claim on RunStore, and ADR-082826-b601 retains the canonical
consumer. No scheduler, execution, authorization or event authority changes.

The strict #459 scheduler closeout scenario remains explicitly abstaining at
`tests/cross_product_parity/test_cross_product_parity.py:70`. Executed with
`MAISTRO_PARITY_MODE=m1-closeout MAISTRO_PARITY_STRICT=1`, its named
`test_schedule_required_scenario_emits_strict_closeout_evidence` fails with
`ScenarioAbstained` and emits `executed=false, status=FAILED`. This repair is
not full issue acceptance or integration approval. Actual configured
scheduler lifespan -> Conductor strict evidence remains UNVERIFIED/failed.

## Executed validation (this repair)

- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (3623 files).
- `MAISTRO_TEST_PG_DSN=<lane-owned pg18> MAISTRO_REQUIRE_PG_LEGS=1 uv run
  pytest packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -x -q`:
  **65 passed, zero skipped**. This includes the retired-policy negative leg,
  persisted-Hive restart regressions, and the new DELETE-outage regression.
- Nine adjacent Hive scheduler suites (scheduler, bounded tick, canonical
  admission, canonical definitions, manual fire, frequency floor, scope,
  workspace scope, timezone health): **176 passed**.
- `DATABASE_URL=<lane-owned pg18> uv run alembic upgrade head`: passed through
  migration 069. `MAISTRO_TEST_PG_DSN=<same> uv run pytest
  packages/maistro-core/tests -k schedul -x -q`: **368 passed**.
- Migration-chain, installed-base Goal-upgrade, capability effect-index
  migration suites against the lane-owned server, sequentially after core
  tests: **28 passed**.
- `uv run python scripts/check-suite-inventory.py`: 21 suites match, Hive
  backend 4354 items (the +3 is recorded above).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1221 = 1221.
- `check-durable-table-inventory.py` (125 tables), `check-doc-links.py`,
  `check-backlog-consistency.py`, `check-test-duplicates.py` (zero duplicate
  groups), all through `uv run python`: passed. `git diff --check`: passed.

## Acceptance accounting

Current reactivation criteria:

1. Canonical enabled/cron/timezone/template edit survives restart: executed
   `test_restart_retains_a_canonical_edit_and_repairs_the_stale_row` on all
   three backends, including real SQL and Hive database reopen.
2. Canonical delete cannot resurrect/fire: executed
   `test_a_deleted_schedule_is_not_resurrected_and_its_stale_row_is_removed`
   and the new failure regression, including far-future due exclusion.
3. Never-imported legacy row migrates once, historical rows cannot override:
   executed legacy-import and tombstoned-history tests on all three backends.
4. Create orphan, repeated/concurrent startup, truthful ack: executed orphan,
   concurrent-startup, UPDATE-outage and DELETE-outage tests. Concurrent
   startups are same-process callers; independent-process import races and
   combined create-projection/compensation failure remain **UNVERIFIED**.
5. Cursors, uniqueness and SQLite/PG concurrency: executed core schedule
   tests and canonical-due tests, including tick/manual interleaving and
   real two-backend parity; projection repair leaves cursors stable.
6. Strict #459 configured lifespan -> Run/Attempt -> Conductor, reopen and
   no stale restore: **FAILED/UNVERIFIED**, as recorded above. Direct tick
   tests are not substituted for a configured product lifespan proof.

Original criteria: production due selection (canonical-only tick test),
projection cannot force due (Hive-row cannot force firing test), no-fire
next_due persistence/future exclusion (canonical-due and admission tests),
SQLite serialized counters (core store tests), occurrence uniqueness
(admission/backend parity and live two-runner tests), and canonical restart
(canonical-due restart tests) all executed. Full E2E/strict lifespan criterion
remains unproven; this is **NEEDS-REPAIR**, not issue completion. No CI run was
triggered and no negative-before/positive-after remote CI claim is made.

Progress checkpoint: checked 1 issue, focused repair committed locally;
strict product-lifespan acceptance remains next. No ledger change and no
unrelated production edits.
