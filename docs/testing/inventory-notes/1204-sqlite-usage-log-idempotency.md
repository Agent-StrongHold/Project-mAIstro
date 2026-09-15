---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #1204 SQLite usage-log idempotency

Four new cases in `packages/maistro-core/tests/quota/test_sqlite_usage_log.py` cover
legacy-schema identity backfill, same-timestamp event identity, forced
overlapping snapshots, and a commit that succeeds before its result is reported
as failed. Each restores the durable log and asserts exact request/token totals,
proving that retries and concurrent flushes cannot inflate quota usage.
