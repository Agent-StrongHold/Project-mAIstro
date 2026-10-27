---
inventory-delta:
  packages/maistro-core/tests: +24
---
# auto-325 round 3: stored-volume health probes for every governed durable table (#325)

Closes the remaining half of the #325 health-metrics criterion. The previous
round shipped last-sweep/failures/backlog-age (see `auto-325-cb9e.md`); this
round adds the *levels* — rows, bytes, and the oldest retained record per
governed table and backend — published by a throttled probe each store's own
purge drives (the probe plumbing lives in `maistro.observability.metrics`
beside the series it publishes, so the promotion import closure is unchanged,
series
`maistro_retention_table_rows`, `maistro_retention_table_bytes`,
`maistro_retention_oldest_record_timestamp`).

New file `packages/maistro-core/tests/observability/test_retention_health.py`
(+11): the probe's own contract — ungoverned table labels are refused (bounded
labels, #818); the throttle publishes once per interval per store key and
re-arms after the interval; a zero interval is the always-publish setting;
gauge `set` overwrites carry the sample's values; `oldest_timestamp` converts
ISO text, unix seconds, unix microseconds and datetimes and degrades to `None`
on unparseable input; a SQLite sample of a missing table is `None` (never a
zeroed sample for a table that does not exist); rows+oldest are read exactly,
and an empty table yields rows 0 with no oldest-record series; dbstat bytes are
the page sum or an honest `None` where the runtime lacks dbstat.

Extended suites (+13 across eight files), each asserting exact or delta values,
never wall-clock luck:

- `tests/runs/test_retention_conformance.py::test_a_purge_publishes_the_spine_tables_stored_volume`
  (memory/sqlite/postgres): after a committed purge the spine tables publish
  their level — one live Run remains, the oldest retained record is exactly
  that Run's `created_at`, NodeRun/Attempt series publish alongside, and
  draining the scope drives `canonical_runs` to 0. PG leg runs where
  `MAISTRO_TEST_PG_DSN` is set.
- `tests/quota/test_sqlite_usage_log.py::test_a_purge_publishes_the_accounting_tables_stored_volume`:
  the raw-vs-aggregate split as levels — the boundary row survives, the folded
  day-bucket appears, the raw table drains to 0 while the aggregate outlives
  it, and the raw table's oldest-record series disappears rather than going
  stale.
- `tests/persistence/test_sqlite_audit.py::test_a_purge_publishes_the_audit_tables_stored_volume`:
  the held-back row's level and creation time publish; a drained log removes
  the oldest-record series.
- `tests/events/test_envelope.py::test_a_sqlite_purge_publishes_the_event_log_stored_volume`
  and `..._postgres_...`: the canonical event log's level after a bounded
  purge; the PG leg asserts a delta between two probes of its own appends
  (the table is shared across the process's PG tests) plus a positive
  `pg_total_relation_size`.
- `tests/persistence/test_session_ttl_purge.py::test_a_purge_publishes_the_conversation_tables_stored_volume`:
  `sessions` and `session_turns` publish alongside the inline TTL purge.
- `tests/tasks/test_idempotency_purge_driven.py::test_a_purge_publishes_the_claim_tables_stored_volume`
  (sqlite/postgres): after a direct bounded purge the claim table's level is
  exactly the one unexpired claim and the oldest record is that claim's
  `created_at` (microsecond precision round-trips).
- `tests/security/test_pg_strikes.py::test_purge_publishes_the_violation_evidence_volume`:
  the named unbounded-evidence table publishes rows, size and oldest record
  through the fake pool boundary, and a second purge inside the interval
  issues no probe queries at all — the throttle gates the sampling, not just
  the gauge writes.
- `tests/persistence/test_pg_audit.py::test_real_postgres_purge_publishes_stored_volume`:
  the PG audit probe publishes a real `pg_total_relation_size` and an empty
  oldest-record series after the drain.
