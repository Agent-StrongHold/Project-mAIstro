---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-325: audit timestamps are stored as UTC instants (purge-order safety)

`SqliteAuditLog.log` now normalizes the signed entry's timestamp to UTC before
storing it. `purge_expired` deletes with a lexical `timestamp < ?` against a
UTC ISO cutoff, so a caller-supplied non-UTC aware timestamp (e.g. an entry
composed from a parsed request time carrying `-05:00`) sorted five hours
younger than it was and could be purged by a cutoff that had not reached it.
This matches the convention `sqlite_outcomes.py` and `sqlite_learnings.py`
already apply. Signature verification is unaffected: the timestamp is
canonical metadata (`_CANONICAL_METADATA_FIELDS`) the proof never covers, and
`datetime.fromisoformat` round-trips the same instant.

New test (+1, `tests/persistence/test_sqlite_audit.py::test_a_non_utc_entry_timestamp_is_stored_as_a_utc_instant`):
a `09:00-05:00` entry is stored as `14:00:00+00:00`, round-trips to the same
instant and verifies, survives a 13:00 UTC purge cutoff, and is removed by a
15:00 UTC cutoff. The test fails against the un-normalized write (stored text
keeps the `-05:00` offset, the 13:00 cutoff lexically deletes the row).
