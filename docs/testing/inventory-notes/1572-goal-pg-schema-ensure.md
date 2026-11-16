---
inventory-delta:
  packages/maistro-core/tests: +2
---

# 1572-goal-pg-schema-ensure

## Why the wiring stopped refusing an unmigrated PostgreSQL pool

The `durable-events` CI leg caught the refusal design from
`1572-goal-wiring-fail-closed`: `create_container` against a bare PostgreSQL
service (that job's whole point — plain `postgres:17`, no pgvector, so the
migration chain from 001 cannot run there) died in `wire_goal_store` with the
`ConfigError`, before the event schema was created. Four container-wiring
tests failed and one failed on a cascade (`TRUNCATE` against tables the failed
wiring never created), which turned the required `durable-events` producer red
and failed `integration-scope` with it.

The durable-events suite pins a contract older than this branch: a Container
wired to a real pool comes up. The event stores honour it with
`ensure_event_schema`; the SQLite Goal twin honours it with `ensure_schema()`;
only the PostgreSQL Goal twin refused. The repair makes the third twin behave
like the other two: `ensure_goal_schema` (`pg_store.py`) creates the
migration-062 tables — idempotent, advisory-locked for concurrent bootstrap —
and `wire_goal_store` calls it before selecting `PgGoalStore`. The anti-split
rule is untouched: a PostgreSQL pool still always answers with the durable
PostgreSQL store, never in-memory, never a SQLite fallback.

## What moved

- `test_wire_goal_store_refuses_an_unmigrated_pg_pool_as_memory` (8
  parametrized cases: absent/partial schema × with/without SQLite) is replaced
  by `test_wire_goal_store_creates_the_schema_an_unmigrated_pg_pool_needs`
  (2 cases): a recording pool double pins the advisory lock, the per-table
  `CREATE TABLE IF NOT EXISTS` DDL, the `PgGoalStore` selection, and —
  preserved from the refusal tests — that no SQLite fallback store is
  initialized. Net −6.
- `test_wiring_brings_a_bare_database_up_with_the_goal_schema` (+1, live):
  a throwaway database that never ran the chain comes up through
  `wire_goal_store` and round-trips a Goal.
- `test_container_pg_durable_events.py` gains
  `test_wiring_a_bare_pool_also_creates_the_goal_schema` (+1): the regression
  itself, at the contract that broke — drop the Goal tables, wire the
  Container, create and read a Goal through it.
- `test_goal_pg_schema_agreement.py` (+6): migration 062 and `pg_store._PG_SCHEMA`
  are two hand-written DDL sources for the same three tables, so — exactly the
  event stores' discipline — a real-server catalogue comparison holds them to
  one schema: columns/types/nullability/defaults, primary keys (the composite
  `(goal_id, revision)` append-only key by name), foreign keys including the
  ON DELETE CASCADE the Subgoal lineage contract lives on, and indexes. Both
  sides render into throwaway schemas, so no migrated database is touched.

Deterministic stub/live split is unchanged from the prior note: live-PostgreSQL
legs skip without `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL`, and the
CI jobs that own servers set `MAISTRO_REQUIRE_PG_LEGS=1` so a skip cannot
masquerade as a pass.
