---
inventory-delta:
  packages/maistro-core/tests: +2
---

# PostgreSQL concurrency evidence for Invocation quota admission (#1196)

Adds two PostgreSQL-gated regressions to
`packages/maistro-core/tests/quota/test_pg_invocation_quota_boundary.py`:

- `test_pg_concurrent_distinct_admissions_cannot_overspend_the_budget` — six
  distinct Invocations raced concurrently through three independent pools
  against one 100-token budget with 40-token bounds: exactly two admitted,
  four durably denied, held total 80 and never above the limit. The
  distinct-invocation overspend race was previously proven only on SQLite
  (two OS processes); this is its real-PostgreSQL proof, exercising the
  transactional advisory lock that serializes the read-hold-write critical
  section.
- `test_pg_concurrent_duplicate_settlement_charges_once` — two replicas
  settling the same completed Invocation concurrently: one evidence row, one
  charge (spent 50, held 0), reservation settled.

Both gate on `MAISTRO_TEST_PG_DSN` like the rest of the file and run for real
in the `coverage (PostgreSQL)` quality job.
