---
inventory-delta:
  packages/maistro-core/tests: +29
---
# fix-m1-1163-durable-legacy-event-cursor

Fixes #1163: `Container.durable_event_cursor` was a plain process-local
`int`. Every restart replayed `durable_event_log` (the legacy-EventBus ->
reactor bridge, ADR-086) from position zero, growing with the whole
retained log rather than with unconsumed events. Correctness survived only
because `InvocationStore.claim` dedupes `(trigger_id, event_id)` -- this
change does not touch that; per ADR-082426-82c7 ("the occurrence is the
claim, not the cursor"), the cursor stays a resume *optimisation*, and
`InvocationStore` stays the correctness backstop.

**New `maistro.events.consumer_cursor`**: a `ConsumerCursorStore` protocol
with in-memory + SQLite implementations (PostgreSQL twin in
`events/pg_stores.py::PgConsumerCursorStore`, sharing that module's
schema/advisory-lock bootstrap), following the same self-contained,
protocol-beside-implementations shape as `EventLogStore`/`InvocationStore`.
`claim(consumer_id, holder, lease_seconds)` returns a `CursorLease`
(position + fencing token) or `None` if another holder's lease is still
live -- of several replicas that might tick the bridge at once, only the
holder re-scans/redispatches a given round, so the rest do not repeat
(idempotent, but wasted) work. `advance(consumer_id, fencing_token,
position)` records a new durable position only for the lease that fencing
token names, with a monotonic `MAX`/`GREATEST` write as a second,
independent guard against a stale or reordered write regressing the
cursor. Same claim/advance shape as `InvocationStore.claim`/
`PgInvocationStore.claim` -- one upsert whose `WHERE` clause is the
exclusion test, `RETURNING` so the decision and the write are one
statement.

**`Container.process_durable_events`** now claims the lease before ticking
(returning the last-known cursor unticked if another replica holds it),
runs `process_events` from the claimed position, and -- only after
`process_events` returns, i.e. only once every event up to the new cursor
has a terminal invocation on every matching trigger -- advances the durable
position. A crash between "processed" and "cursor written" costs at most a
replay of already-settled, already-idempotent work; it never skips an
event still in flight. `Container` gained `consumer_cursor_store` (wired
in-memory/SQLite/PostgreSQL alongside the other three durable-event stores
in `create_container`, `_wire_sqlite_durable_events`,
`_wire_pg_durable_events`) and `_durable_events_holder` (a per-instance
UUID identifying this `Container` as a lease holder across repeated
ticks/renewals).

**Tests (+29, all in `packages/maistro-core/tests`).**
`tests/events/test_durable_store_conformance.py` gains a `cursor_store`
fixture (parametrized over memory/SQLite/PostgreSQL, the PostgreSQL leg
skipping without `MAISTRO_TEST_DATABASE_URL` like its siblings) and
`TestConsumerCursorStore`, 9 test functions x 3 backends = 27 node IDs:
a fresh consumer starts at position 0; `advance` persists the position for
the next `claim`; a second holder is refused while the lease is live; the
same holder can renew before expiry (keeping its fencing token); an
expired lease can be taken over (with a new token); a stale fencing token
cannot `advance` the cursor after a takeover; `advance` never moves the
position backwards even when asked to; different consumer ids do not share
a cursor; and of many racing claims on one consumer, exactly one succeeds.

`tests/test_container_wiring.py` gains 2 new tests (not parametrized):
`test_durable_event_cursor_survives_a_restart` builds a container against
a durable `sqlite:///...` file, ticks it past two events, "expires" its
own lease (standing in for however long a real restart takes to notice and
wait out a dead holder), then builds a second container against the same
file and proves (a) probing the lease alone already reports position 2,
not 0, and (b) a real tick after adding one more event redelivers only
that new event (`[3]`), not the whole log (`[1, 2, 3]`) -- the exact
"restart after partial replay processes only the remaining eligible
events" acceptance criterion.
`test_a_held_tick_lease_stops_a_second_replica_from_reticking` proves a
tick under a live lease held by a different replica is a no-op rather than
a redundant re-scan.

Full `packages/maistro-core/tests/` (9950 collected) passes. `ruff check`/
`ruff format --check` clean on every touched file. `mypy --strict
packages/maistro-core/src` clean.
