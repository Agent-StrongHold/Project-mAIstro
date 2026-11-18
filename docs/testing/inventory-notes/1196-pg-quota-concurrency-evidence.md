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

## Real-PostgreSQL execution evidence (local, CI-identical image)

Executed against a local `pgvector/pgvector:pg17` container (the same image,
user/db, and DSN shape the `coverage (PostgreSQL)` job provisions):

- Both new tests pass: `uv run pytest
  packages/maistro-core/tests/quota/test_pg_invocation_quota_boundary.py -k
  "concurrent_distinct_admissions or concurrent_duplicate_settlement"` —
  2 passed.
- Whole boundary file passes on the real server: 27 passed, 0 skipped.
- Full quota battery with the DSN set: `packages/maistro-core/tests/quota
  packages/maistro-core/tests/test_container_quota_admission.py` — 287 passed,
  0 skipped (the 31 PG legs the writing environment skipped now execute).
- The tests catch the regressions they name: with
  `pg_advisory_xact_lock` in `PgInvocationQuota.reserve` replaced by a no-op,
  the overspend test fails (`['admitted', 'admitted', 'admitted', ...]` — a
  third distinct Invocation gets in); additionally removing the `FOR UPDATE`
  from the settlement reservation read makes the duplicate-settlement test
  fail (`invocation_quota_evidence_pkey` UniqueViolationError under the
  concurrent gather).
