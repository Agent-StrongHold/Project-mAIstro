---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-325 repair round: event_log probe coverage and probe-key independence

Three additions, each pinning a defect the L325 verify round recorded against
cc549e3c5; each was demonstrated to fail against the pre-fix module (details
below).

`tests/events/test_durable_log.py` (+1):
`test_a_sqlite_purge_publishes_the_delivery_log_stored_volume` — the durable
delivery log's `purge_expired` deleted rows but published no stored-volume
health, so a delivery log nobody bounded was invisible in every level metric
(the sweep contract's stored-volume clause). The test drives a real purge over
an in-memory SQLite store: one backdated row purged, `event_log` rows == 1
with the surviving row as the oldest record; a full drain drops the
oldest-record series while rows goes to 0 (honest absences, not stale
levels).

`tests/events/test_durable_store_conformance.py` (+1):
`test_pg_purge_publishes_the_delivery_log_stored_volume` — the PostgreSQL leg
of the same contract for `PgEventLog.purge_expired`, plus the per-table size
only PostgreSQL can measure. Skips without `MAISTRO_TEST_DATABASE_URL`;
truncates first so the published levels are its own rows.

`tests/security/test_pg_strikes.py` (+1):
`test_the_two_security_stores_probe_independently` — `PgStrikeTracker` and
`PgRateLimiter` published under the same throttle key `security:postgres`, so
a sweep loop driving both purges back-to-back starved whichever ran second
into publishing nothing, forever. The limiter now probes under its own
`security_rate_limits:postgres` key; the test drives both purges back-to-back
through a fake pool and asserts both tables' series publish.

Pre-fix demonstrations (identical scenarios against the parent of the fix
commit, run in a scratch `git worktree` of the pre-fix head with these test
files copied in): the two probe tests failed with empty series lists
(`assert [] == [1.0]`), and the independence test failed with
`security_rate_limits` absent while `security_violations` published —
the exact dead-series shape the finding recorded. The fragile shared-database
assertion fix in `test_pg_event_envelope.py` (+0 nodes; assertion rescoped)
was demonstrated by seeding a foreign old row in the shared database: the old
exact-global-count assertion failed `5 == 2`-style while the stream-scoped
assertions held.
