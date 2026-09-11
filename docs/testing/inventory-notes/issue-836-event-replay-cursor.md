---
inventory-delta:
  packages/maistro-core/tests: +8
---
# Issue #836 event replay acknowledgement

Adds coverage for the durable legacy-event reactor cursor and authoritative bus bridge:

- replay acknowledgements are monotonic and reject invalid positions;
- SQLite replay progress survives a store/connection restart;
- an authoritative pre-handler subscriber failure is surfaced and cannot run a trigger;
- a failure from the container's durable-log bridge is explicit and leaves no bus history;
- a container restart resumes after the acknowledged event and processes newly appended work.

The production cursor is stored alongside each durable event log and keyed by the reactor consumer identity. `Container.process_durable_events()` reads that durable acknowledgement before processing and writes it only after the bounded processing pass settles. A crash before acknowledgement can replay successful invocation rows, which the existing invocation idempotency key handles without duplicating the handler effect.
