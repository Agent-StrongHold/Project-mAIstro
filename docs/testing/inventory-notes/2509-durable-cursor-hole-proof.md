---
inventory-delta:
  packages/maistro-core/tests: +12
---
# 2509-durable-cursor-hole-proof

Issue #2509 (M1-E1, P1 silent event loss): `Container._gap_safe_position`
advanced the durable consumer cursor past an unresolved `event_log` id hole
once the hole had been open for `durable_event_hole_grace_s` (60 s) — but a
PostgreSQL transaction can hold an allocated `BIGSERIAL` id past any timeout
and commit it afterwards. Crossing the hole on elapsed time therefore
permanently excluded the late event from every later ``id > cursor`` read,
restart and lease takeover included. The two tests that encoded the assumption
(`test_a_hole_that_outlives_the_grace_is_an_aborted_append`,
`test_each_hole_gets_its_own_grace`) asserted exactly this and are replaced.

**What changed (behaviour).** The durable position now crosses a hole only on
the log's own durable evidence that the hole is *terminally absent*: the
allocating transaction ended without committing and no future transaction can
make the id visible. `EventLogStore` gains `prove_holes_absent`, with three
implementations. PostgreSQL: a transaction that has called `nextval` holds a
granted lock on `event_log_id_seq` until it commits or aborts, so a granted
lock in `pg_locks` means some append may yet commit a hole (prove nothing);
no lock plus a still-invisible id in a fresh read means the append rolled
back, and since a sequence never hands an id out twice, the id is crossed
safely — database evidence, never elapsed time. SQLite: taking the write lock
(`BEGIN IMMEDIATE` under a zero busy timeout) proves no writer transaction is
live, and a re-read inside that lock answers terminally. In-memory: appends
are synchronous and nothing can prove an id absent, so the honest answer
proves nothing and the cursor holds below the hole. `_gap_safe_position` lost
its `now` parameter, its per-holder first-seen map, and
`durable_event_hole_grace_s` / `DEFAULT_HOLE_GRACE_SECONDS` ceased to exist.
ADR-086's gap-policy bullet records the new contract.

**Tests (+12, all in `packages/maistro-core/tests`).**
`tests/test_container_wiring.py` (+1 net): the two grace tests become
`test_an_unproven_hole_holds_the_cursor_no_matter_how_long_it_lingers` (an
unproven hole pins the durable position and the replay acknowledgement across
arbitrarily many ticks — no clock input exists for a grace to consume),
`test_only_durable_evidence_moves_the_cursor_past_a_hole` (the position
crosses exactly the holes the log proves absent and never passes the first
unproven one, via a `_ProvingLog` shim answering `prove_holes_absent` from a
test-controlled set), and
`test_durable_evidence_advances_the_cursor_past_a_rolled_back_append` (a
full `process_durable_events` loop where proof arrives mid-stream and moves
the persisted position without redelivering settled events).

`tests/events/test_durable_store_conformance.py` (+8): the universal
`prove_holes_absent` invariants over all three backends (a visible id is
never absent; proving no holes proves nothing) plus the in-memory honest
refusal; a real two-connection SQLite test on a file database (a live writer
transaction proves nothing, a rolled-back one is proven absent); and a
PostgreSQL two-connection test (gated on `MAISTRO_TEST_DATABASE_URL`):
connection A allocates id 2 and holds its transaction open while the pool has
committed id 3 — the proof comes back empty for as long as A can commit,
then proves 2 absent once A rolls back, and confirms the sequence never
handed 2 out again.

`tests/events/test_container_pg_durable_events.py` (+2, PostgreSQL-gated):
the issue's end-to-end oracles on a real server. One: two independent
connections, A holding id 2 open while id 3 committed — two production ticks
and a lease takeover by a second container all hold the durable cursor at 1;
after A commits, the ordinary path delivers id 2 (once, deduped where
already settled) and the position settles at 3 with id 3 retained. Two: A
rolls back and the next tick crosses the hole on durable evidence — bounded
forward progress, no sleep and no timer.

**Demonstrated regression sensitivity.** Against the pre-fix sources the new
evidence-gated tests fail (the old `_gap_safe_position` demanded a `now` —
crossing was time-parameterized — and crossed without querying any proof),
while the old grace test passed, i.e. it was green precisely on the behaviour
the issue calls silent event loss.

**Legs.** `packages/maistro-core/tests/events` + `tests/test_container_wiring.py`
with `MAISTRO_TEST_DATABASE_URL` pointing at a real PostgreSQL 18: full
`packages/maistro-core/tests` (17955 passed, 1308 skipped) and Ruff clean;
`check-vulture-baseline.py` (1217 = 1217, candidate = base),
`check-radon-baseline.py` (124 = 124), reachability, wiring-reads,
contract-markers, doc-links, ADR-index and execution-lifecycles gates all
pass. Mypy clean on `maistro.events` and `container.py`.
