---
inventory-delta:
  packages/maistro-core/tests: +7
---
# Issue #836 event replay acknowledgement

Adds coverage for the durable legacy-event reactor cursor and authoritative bus bridge:

- replay acknowledgements are monotonic and reject invalid positions;
- SQLite replay progress survives a store/connection restart;
- an authoritative pre-handler subscriber failure is surfaced and cannot run a trigger;
- a failure from the container's durable-log bridge is explicit and leaves no bus history.

Delta corrected from +8 to +7 during the develop sync: upstream develop now
carries its own container restart-resume and tick-lease cursor tests
(`test_durable_event_cursor_survives_a_restart`,
`test_a_held_tick_lease_stops_a_second_replica_from_reticking` in
`test_container_wiring.py`), so the restart bullet is no longer a net-new
count of this branch. The node-ID diff against the merge base confirms the
seven remaining additions.

The production cursor is stored alongside each durable event log and keyed by the reactor consumer identity. `Container.process_durable_events()` reads that durable acknowledgement before processing and writes it only after the bounded processing pass settles. A crash before acknowledgement can replay successful invocation rows, which the existing invocation idempotency key handles without duplicating the handler effect.
