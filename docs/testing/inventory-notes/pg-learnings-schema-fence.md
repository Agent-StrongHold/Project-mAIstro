---
inventory-delta:
  packages/maistro-core/tests/persistence/test_pg_learnings.py: +1 collected test
  (test_ensure_schema_fences_ddl_behind_advisory_lock); FakeConnection gains a
  transaction() recording double so the fence shape is assertable without a
  live database.
---

# #860 F7 — fence PgLearningStore.ensure_schema behind a transaction advisory lock

## What broke

`PgLearningStore.ensure_schema` issued `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` and two `CREATE INDEX IF NOT EXISTS` statements as three bare
autocommit statements. `CREATE INDEX IF NOT EXISTS`'s existence check and its
insert into `pg_class` are not atomic across processes: two replicas booting
against the same database can both pass the check and one dies with a
duplicate key on `pg_class_relname_nsp_index`. Reproduced live on
pgvector/pg18 during the #860 two-replica concurrent boot (finding F7,
round 1).

## The fix

`packages/maistro-core/src/maistro/persistence/pg_learnings.py` now runs the
whole upgrade inside one transaction guarded by a transaction-scoped advisory
lock (`_SCHEMA_LOCK_KEY = 0x6D61_656C`, "mael"), the same pattern as
`events.pg_envelope.ensure_canonical_event_schema` ("mae1") and
`events.pg_stores` ("mais"). Concurrent booters serialize; the loser waits and
then sees the index already there. The key namespace is distinct from every
other advisory-lock user in the repo.

## The test

`test_ensure_schema_fences_ddl_behind_advisory_lock` asserts, against the
file's existing SQL-recording fake:

- exactly one transaction wraps the upgrade (BEGIN first, COMMIT last);
- `pg_advisory_xact_lock($1)` is the first statement inside it, keyed to
  0x6D61656C;
- the three DDL statements run in order inside the fence and nothing else
  executes between lock and commit.

The fake `FakeConnection.transaction()` records enter/exit as calls, so the
transaction boundary itself is asserted, not assumed.

## Live corroboration

Repair round 2's scratch soak (two concurrent replica boots, documented in
`m3a-860-multi-replica-soak.md`) completed a double boot in 10.9s with both
replicas ready — the same boot path that crashed on pg18 in round 1.
