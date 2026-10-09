---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #860 — retain the schema fence assertion after the learning-stage merge

Fresh validation at `94332bb86980aea66359930f04c59c0b0d1fedf2` failed
`test_ensure_schema_fences_ddl_behind_advisory_lock`: its historical three-DDL
expectation omitted the five learning-stage upgrade statements now executed by
production `PgLearningStore.ensure_schema()`.

The existing test now checks the complete ordered eight-statement upgrade
(scope column, three stage columns, audit table, audit index, two scope indexes).
The same assertions still require one transaction, the advisory lock first,
and commit last. No production DDL or concurrency gate is removed. No tests
are added, removed, or renamed; the inventory delta is zero.

This is SQL-recording fake coverage of production method ordering, not live
PostgreSQL concurrency or exact-RC soak evidence. Validation and mutation results
are recorded in `docs/testing/soak/issue-860-a30f3c5f-repair.md`.
