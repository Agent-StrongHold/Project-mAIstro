---
inventory-delta:
  packages/maistro-core/tests: +7
---
# Issue #42: live PostgreSQL Invocation contention

Adds `capabilities/test_pg_invocation_contention.py` to close the specific
fake-pool-only evidence gap recorded by the previous repair. Uses the existing
migrated `pg_pool` fixture and an independent asyncpg pool with production JSON
codecs. No production authority, schema, ledger, or gate policy is changed.

- Four persisted claim states (CREATED/RUNNING/COMPLETED/UNKNOWN) each refuse a
  competing claim under another physical NodeRun with the same logical scope.
- Two service races rendezvous after both history reads, hold the winning
  provider open until the loser is refused, and assert one physical dispatch.
  Fresh service/store objects read completed/ambiguous facts through the other
  connection pool; later physical identities replay/refuse without resolving a
  provider. Original Invocation-to-Attempt correlation is retained.
- One stale-writer test verifies PostgreSQL revision CAS preserves a terminal
  fact against a write based on another worker's earlier read.

Requires `MAISTRO_TEST_PG_DSN`; an absent server skips these tests, not evidence
of acceptance. This is not a process-death test or a combined Event/Run trace.
Validation and mutation evidence are recorded in the repair report.
