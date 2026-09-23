---
inventory-delta:
  packages/maistro-core/tests: +10
  tests/migrations: +0 (pin moved; 11 existing cases now run against the revision that creates `quota_usage_events`)
---
# #1204 SQLite usage-log idempotency

Four new cases in `packages/maistro-core/tests/quota/test_sqlite_usage_log.py` cover
legacy-schema identity backfill, same-timestamp event identity, forced
overlapping snapshots, and a commit that succeeds before its result is reported
as failed. Each restores the durable log and asserts exact request/token totals,
proving that retries and concurrent flushes cannot inflate quota usage. Two additional persistence cases exercise the shared quota tracker protocol: memory, SQLite, and PostgreSQL all deduplicate a repeated event identity and reject identity reuse with different usage.

## Merge resolution against trunk's serialized schema upgrades (#1461)

Trunk landed `serialized_schema_upgrade` (per-connection lock + `BEGIN
IMMEDIATE`) on top of the pre-#1204 watermark implementation, so the merge
conflicted in both `ensure_schema` methods. Resolution combines both:
`SqliteUsageLog.ensure_schema` runs the event-id column backfill and unique
identity index inside the shared discipline, nested under the instance
operation lock so the migration excludes `snapshot`/`restore` on the same
connection; `SqliteQuotaTracker.ensure_schema` creates `quota_usage` and
`quota_usage_events` inside the shared discipline. Trunk's `SqliteUsageLog`
watermark and per-scope timestamp dedup are fully replaced by the event
identity semantics this issue owns. Verified live against a pgvector:pg18
container: the legacy timestamp-only table upgrades and backfills
`legacy:<rowid>` identities, three overlapping snapshots restore exactly once
(2 requests / 25 total tokens for a 15-token backfilled row plus a 10-token
event), and a repeated `record_usage(event_id=...)` keeps `request_count=1`.

## Migration chain linearization

The branch's migration previously shared trunk's renumbered 033-035 space and
sat as a second alembic head, which fails CI's `alembic upgrade head`. It is
renamed to `039_quota_usage_event_identity` with `down_revision = "038"`,
giving a single head. `tests/migrations/test_migration_chain.py` applies the
full chain to an empty PostgreSQL database, and the downgrade/upgrade cycle
recreates `quota_usage_events` — both run green against the live server.

## Pinned-revision store suite follows its own convention

`tests/migrations/test_quota_and_session_stores.py` pins the revision the
durable stores run against; `PgQuotaTracker` now touches `quota_usage_events`,
which the old pin (023) predates. Per the suite's documented drift procedure
(the #327 move), the pin moves to `039_quota_usage_event_identity`; the
fixture's plain upgrade-from-empty already exercised the `vector`-dependent
001, so no new image coupling is introduced. All 11 cases pass against the
migrated scratch database.
