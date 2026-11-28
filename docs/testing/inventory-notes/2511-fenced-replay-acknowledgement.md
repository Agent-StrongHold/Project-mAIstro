---
inventory-delta:
  packages/maistro-core/tests: +14
---
# 2511-fenced-replay-acknowledgement

Issue #2511 (M1-E1, P2 durable acknowledgement integrity / fencing):
`Container.process_durable_events` discarded the boolean result of
`ConsumerCursorStore.advance` and then unconditionally published
`durable_event_log.acknowledge_replay(consumer, new_cursor)` and
`self.durable_event_cursor = new_cursor`. `PgEventLog.acknowledge_replay`
monotonically updates the independent `event_replay_cursors` table and carries
no lease token of its own, so a replica whose fencing token had just been
refused — its lease lapsed mid-batch and another holder took the cursor over —
still wrote its rejected position onto the log and reported it as local
progress. The public log acknowledgement could thereby claim a position the
canonical fenced cursor explicitly declined, possibly one above the
authoritative cursor under concurrent out-of-order/hole scenarios (#2509).

**What changed (behaviour).** The tick now checks `advance`'s result. On
refusal it acknowledges nothing on the log and claims no progress: it re-reads
the authoritative position through the new `ConsumerCursorStore.current_position`
(a read-only projection of the same cursor store — in-memory, SQLite and
PostgreSQL twins — not a second authority), mirrors it locally, and returns it.
On acceptance it derives the acknowledgement from the authoritative cursor
re-read from the store rather than from this tick's own `new_cursor`, so a
takeover in the window between the primary advance and the secondary
acknowledgement can only ever publish a position the primary cursor explicitly
accepted (the store's monotonic write guarantees the re-read is ≥ the accepted
position). Handler `InvocationStore` claims, the durable `EventLog`, the
monotonic primary cursor, fencing, restart resumption and idempotent replay are
unchanged; a crash between the two writes still costs at most a replay of
already-settled idempotent work, leaving the acknowledgement lagging the cursor
conservatively until the next settled tick carries it forward. ADR-086's
`#1163` amendment gains the **Fenced acknowledgement** bullet recording this
contract.

**Tests (+14, all in `packages/maistro-core/tests`).**
`tests/events/test_durable_store_conformance.py` (+9 = 3 tests × the
memory/sqlite/postgres backend parametrization): `current_position` reads zero
for an unknown consumer, reads back an accepted advance for any reader, and —
the #2511 invariant — stays untouched by a stale-token advance, so the
authoritative position a rejected holder re-derives is exactly what the current
holder owns.

`tests/test_container_wiring.py` (+3, backend-free so they run on every CI
leg): `test_a_rejected_advance_acknowledges_nothing_and_reports_the_authoritative_cursor`
performs the takeover mid-batch from inside the injected handler, asserts the
tick settled all three events yet returned/mirrored/acknowledged only the
authoritative position 0 even though it processed past the new holder, and then
re-derives the settlement idempotently after retaking the lease (delivered once,
cursor 3, acknowledgement 3, mirror 3);
`test_a_takeover_between_the_advance_and_the_acknowledgement_publishes_the_authoritative_position`
hands the lease over inside a cursor-store shim after the advance is accepted
and the new holder advances further, asserting the tick reports, mirrors and
acknowledges the authoritative 9 — never its own pre-takeover view 2;
`test_a_kill_between_the_cursor_write_and_the_acknowledgement_leaves_no_contradiction`
(sqlite file database) raises out of `acknowledge_replay` between the two
writes, restarts a fresh container on the same database, and asserts the
checkpoint is conservative (cursor 3 leads, acknowledgement 0 lags, never
ahead) and that the next settled tick reconciles primary cursor,
acknowledgement and local mirror to 4 from the existing authority alone.
Against the pre-fix code both takeover tests fail on their acknowledgement
assertions — the old tick wrote `new_cursor` unconditionally.

`tests/events/test_container_pg_durable_events.py` (+2, PostgreSQL-gated on
`MAISTRO_TEST_DATABASE_URL`, exercised locally against a real migrated server
via `ensure_event_schema`): the issue's two-worker oracle over **two
independent asyncpg pools**. One: replica A pauses mid-batch inside its handler
on an `asyncio.Event` barrier, the test forces the lease to lapse through
replica B's pool (`UPDATE consumer_cursors SET lease_expires_at = 0`) and B
claims with its own holder id; A resumes, settles all three events
(`handler_invocations` count 3), and its refused advance leaves
`event_replay_cursors` empty and both replicas reporting position 0; B's tick
then dedupes (no dispatch repeated), advances to 3, and both pools read the
same consistent cursor and acknowledgement back. Two: a takeover injected
between A's accepted advance and its acknowledgement publishes only the
authoritative position (9) on `consumer_cursors` and `event_replay_cursors`
alike, and B continues from it with nothing contradictory to reconcile.
