---
inventory-delta:
  packages/maistro-core/tests: +10
---
# #1204 SQLite usage-log idempotency

Four new cases in `packages/maistro-core/tests/quota/test_sqlite_usage_log.py` cover
legacy-schema identity backfill, same-timestamp event identity, forced
overlapping snapshots, and a commit that succeeds before its result is reported
as failed. Each restores the durable log and asserts exact request/token totals,
proving that retries and concurrent flushes cannot inflate quota usage. Two additional persistence cases exercise the shared quota tracker protocol: memory, SQLite, and PostgreSQL all deduplicate a repeated event identity and reject identity reuse with different usage.
