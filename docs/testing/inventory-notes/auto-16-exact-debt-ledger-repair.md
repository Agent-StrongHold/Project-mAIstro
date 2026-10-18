---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-16 exact-debt-ledger repair: the bridge writes the log's replay acknowledgement

The merge-queue evaluation of this branch failed the `exact-debt-ledger` job
with four unauthorized Vulture identities, all one name:
`EventLogStore.acknowledge_replay` (the protocol declaration, the in-memory
and SQLite implementations, and the PostgreSQL one). The finding was real, not
scanner noise. This branch originally shipped `process_durable_events`
acknowledging the settled position on the durable log (#836), but the develop
syncs that brought #1163's `ConsumerCursorStore` (claim lease + fencing)
replaced that loop wholesale, leaving `event_replay_cursors` — a table revision
064 deliberately manages in PostgreSQL — with no production writer at all.

The repair restores the write inside the #1163 loop rather than banking the
debt: after a tick settles real progress, the same gap-safe position is
acknowledged on the log under `LEGACY_BRIDGE_CONSUMER_ID`, beside the existing
cursor-store advance. Both stores stay monotonic, the invocation claim remains
the one correctness backstop, and a hole is never claimed as settled.

The three node IDs pin the contract:

- `test_a_settled_tick_acknowledges_the_log_and_an_empty_tick_does_not` — a
  settled tick writes the acknowledgement; an empty tick writes neither store;
- `test_the_acknowledgement_holds_below_a_hole_and_agrees_with_the_cursor_store`
  — with an uncommitted id hiding below the cursor, the log acknowledgement
  stops at the same gap-safe position the cursor store persists, and both move
  to 3 only after the hole fills;
- `test_the_log_replay_acknowledgement_survives_a_restart` — a fresh Container
  over the same SQLite database reads the previous container's settled position
  off the log before ticking anything itself (in-process mirror still 0).

All three fail against the pre-repair loop (the acknowledgement never happens)
and pass with it, so the regression this fix names is the regression they
catch. The Vulture ledger itself is unchanged: the identities left the scan
because the API regained a production caller, not because rows were reclassified.
