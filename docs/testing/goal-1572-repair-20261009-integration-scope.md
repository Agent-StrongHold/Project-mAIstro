# Goal #1572 bounded CI repair — 2026-10-09 (round: integration-scope)

## Frozen scope

Assigned: repair issue #1572 on branch `auto-1572` at head `90df5d7dfa1b`
(develop base `d592654aca61`). Driver-named CI failure: `integration-scope`.
No GitHub mutations; no ledger/grant edits.

## Failure chain, verified first-hand (read-only GitHub evidence at PR #1938 head `063ab7d1dad3`)

Check runs at the PR head (gh API, read-only):

| check | conclusion | cause |
|---|---|---|
| durable-events | **failure** | 4 tests in `packages/maistro-core/tests/events/test_container_pg_durable_events.py`: `ConfigError: PostgreSQL pool is missing the canonical Goal tables` ×3, cascade `UndefinedTableError: relation "handler_invocations" does not exist` ×1 |
| integration-scope | **failure** | fail-closed aggregator: `durable-events` is in the required set for this candidate's changed paths (scope: docker_build, durable_events, hive_e2e, object_storage, postgres, strike_ladder, wheel_imports); all other required legs succeeded |
| test / Quality gate / Coverage gate | failure | the one known external blocker (below), not this round's repair target |

Root cause: `wire_goal_store` refused an unmigrated PostgreSQL pool with
`ConfigError` at Container startup. The `durable-events` CI job runs a bare
`postgres:17` (deliberately not pgvector — the migration chain from 001 needs
`CREATE EXTENSION vector`, per the workflow's own comment) and pins the
contract that `create_container` comes up against it (`ensure_event_schema`;
`test_wiring_creates_the_schema_it_needs` even drops the event tables and
expects wiring to recreate them). The refusal killed the Container before the
event schema existed; every Goal table in that database is one idempotent
statement away, and the SQLite Goal twin already self-heals the same way
(`ensure_schema`), so the refusal was the outlier among the three backends.

## Repair

`ensure_goal_schema(pool)` (`maistro/goals/pg_store.py`): the migration-062
DDL mirrored statement-for-statement, `CREATE TABLE IF NOT EXISTS`, serialized
by a transaction-scoped advisory lock (`0x676F_616C`, distinct from the event
stores' `0x6D61_6973`) — the exact discipline `ensure_event_schema`
documented. `wire_goal_store` calls it before selecting `PgGoalStore`; the
anti-split rule is unchanged (a PostgreSQL pool always answers with the
durable PostgreSQL store). Migration 062 stays the managed-deployment path;
the two DDL sources are held to one catalogue by a new agreement test, the
event stores' own pattern (`tests/migrations/test_event_schema_agreement.py`).

## Validation executed

Against a local `pgvector/pgvector:pg17` container (`127.0.0.1:5577`):

- `DATABASE_URL=… uv run alembic upgrade head` — chain applies through 062.
- `uv run pytest packages/maistro-core/tests/goals -q` with live DSN +
  `MAISTRO_REQUIRE_PG_LEGS=1` — **70 passed** (conformance PG leg, restart
  readback, run binding, wiring incl. two new live tests, agreement test).
- `uv run pytest packages/maistro-core/tests/events -q` against a **bare**
  database (fresh `bare_events_test`, no migrations — CI's exact shape) —
  **383 passed**, including the 4 previously failing tests and the new
  regression test.
- `uv run pytest tests/migrations/test_event_schema_agreement.py` (bare DB) —
  5 passed; `tests/migrations/test_goal_installed_base_upgrade.py`
  `tests/migrations/test_migration_chain.py` (migrated DB) — 25 passed.
- `packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py`
  + `packages/maistro-core/tests/test_container_postgres.py` (migrated DB) —
  17 passed.

Gates:

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass.
- CI-exact `uv run mypy packages/maistro-core/src …` (all ten packages) —
  "Success: no issues found in 1041 source files".
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1323 = 1323, pass; no
  ledger amendment needed.
- `uv run python scripts/check-m1-convergence-freeze.py --base d592654aca61` —
  pass. `scripts/check-durable-table-inventory.py` — 110 tables ok.
- `scripts/check-suite-inventory.py` — 17 suites ok after recording the +2
  delta (`inventory-notes/1572-goal-pg-schema-ensure.md`).

## Known, external, unchanged

`scripts/check-execution-lifecycles.py` (CI-exact) still exits 1:
`maistro.goals.model::GoalStatus: NEW work-state vocabulary … no already-landed
authorization`. The grant must land on `quality/ratchet-authorizations.json`
**on develop first** (`ratchet_provenance.load_authorizations` reads the base;
a candidate-side grant authorizes nothing), then this branch rebases. That is
a GitHub mutation outside this lane's powers; `test`, `Quality gate` and
`Coverage gate` stay red on it, and no in-branch edit can clear them. This
repair does not touch `quality/` and does not weaken any gate.
