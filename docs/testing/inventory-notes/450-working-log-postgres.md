---
inventory-delta:
  packages/maistro-core/tests: +21
---
# 450-working-log-postgres

Issue #450 repair round: the per-Workspace working log gained its PostgreSQL
durable twin (#301, M4-H / #105), so a `postgresql://` deployment retains
observations across restart instead of falling back to the in-process log.

What moved the count, all in `packages/maistro-core/tests/memory/`:

- `test_working_log_store_conformance.py` — the parametrized `store` fixture
  gained a `"postgres"` leg (+7 of the conformance cases) and a new
  `TestPostgresRestart::test_log_and_results_survive_a_fresh_pool`
  (+1): the durable leg's reason to exist, a new pool re-reading what the
  first process retained.
- `test_working_log_pg_schema_agreement.py` — new file, 6 tests: migration 071
  vs `pg_store._PG_SCHEMA` compared against a real server's catalogue
  (columns, identity generation on `seq`, primary keys, absence of foreign
  keys, indexes).
- `test_working_memory.py` — three wiring tests (+7 incl. parametrized
  splits): recording-pool backend selection, real-server bare-database
  bring-up with retention across a new pool and the driven purge, and the
  Container-seam selection of the PG twin when only `pg_pool` is present.

The PostgreSQL cases skip without `MAISTRO_TEST_PG_DSN` /
`MAISTRO_TEST_DATABASE_URL` and fail instead of skipping under
`MAISTRO_REQUIRE_PG_LEGS`, so the ci.yml postgres job step added in the same
change runs them against the real service; the memory/sqlite legs and the
non-PG assertions run everywhere as before.
