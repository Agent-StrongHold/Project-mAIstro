---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/maistro-turing/backend/tests: +1
---
# auto-325 round 4: cursor survival under event retention, accounting dedup, pg probe units

Seven additions in three files, each pinning a retention defect Codex review
found on d33f3b4bf; every one was demonstrated to fail against the pre-fix
module by running the identical scenario against the committed code.

`tests/events/test_envelope.py` (+4 node IDs: two tests over the memory/sqlite
`store` params, the sqlite leg asserting, memory skipped as purge-less):

- `test_sequence_continues_after_a_purge_empties_the_stream`: retention may
  delete every event of a stream; allocation that read only the surviving
  `MAX(sequence)` restarted the emptied stream at 1, so a reader resuming from
  `after_sequence=N` silently missed the new events. The durable per-stream
  high-water mark (`canonical_event_stream_watermarks`, advanced in the append
  transaction on both backends) is the allocation floor; the next event
  continues at 3 and `list_stream(after_sequence=2)` returns it.
- `test_sequence_continues_after_a_purge_removes_the_highest_sequence`:
  timestamps need not follow append order, so a purge can remove the highest
  sequence while a lower-numbered row survives; pre-fix allocation reused the
  deleted number (next = 2). Post-fix the mark holds it at 3.

`tests/events/test_pg_event_envelope.py` (+1): the PostgreSQL leg of the same
contract — two appends, a full purge, and the next append at sequence 3 —
against a real server (skips without `MAISTRO_TEST_DATABASE_URL`), cleaning up
both its event rows and its watermark row.

`tests/persistence/test_session_ttl_purge.py` (+1): the post-purge probe for
`sessions`/`session_turns` must decode TIMESTAMPTZ as `datetime`
(`oldest_unit="datetime"`); the `unix_s` conversion floated the asyncpg
`datetime`, caught the `TypeError`, and published no oldest-record series for
tables that have one. Driven through the public `purge_expired` over a fake
pool whose `MIN(timestamp)` is a real `datetime`; the published
`maistro_retention_oldest_record_timestamp` equals that instant on both tables.

`tests/quota/test_sqlite_usage_log.py` (+1): regression for the review finding
that a `snapshot` after `purge_expired` resurrected an idle scope's purged
event — its durable row was gone, so the flush reinserted it and the next
sweep aggregated it a second time (snapshot → purge → snapshot → purge doubled
one 7-token event to 14). The durable `usage_purge_watermarks` table, written
in the purge's own transaction, lets `snapshot` skip retired events; the test
asserts the aggregate stays 7 and `usage_events` drains to 0.

`packages/maistro-turing/backend/tests/test_chat.py` (+1):
`test_a_stale_tracking_entry_frees_its_window_slot` — a tracked Run the store
already deleted occupies no retention window: dropping the stale entry must
decrement the precomputed excess, else with `max_retained=2` a stale entry +
one terminal Run + the new admission evicted the terminal Run (pre-fix
deleted it; post-fix both live entries survive). Insertion order puts the
stale entry before the terminal Run, which is what lets the loop reach it
first; the existing stale-entry test could not see this because its single
live Run was non-terminal.
