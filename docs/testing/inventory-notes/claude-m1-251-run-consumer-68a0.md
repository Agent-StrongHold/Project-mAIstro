---
inventory-delta:
  packages/maistro-core/tests: +22
---
# claude-m1-251-run-consumer-68a0

Twenty-two new node IDs for the canonical Run consumer (#251, ADR-082826-b601),
purely additive:

- 12 in `tests/runs/test_consumption.py`: the tick executes an admitted
  single-node schedule Run to COMPLETED with canonical NodeRun/Attempt records;
  CREATED/foreign-source/multi-node Runs are never claimed; failed work parks
  and is not silently retried; concurrent ticks execute once (the QUEUED→RUNNING
  transition is the claim); a drained backlog is a no-op; and
  `RunStore.list_by_status` conformance across memory/SQLite/PostgreSQL spines
  (6 parametrized IDs) plus the ungated reference-store AC pin.
- 9 more in `tests/runs/test_consumption.py`, on the failure arms: a lost
  QUEUED→RUNNING claim is skipped without touching the Run; an infrastructure
  failure before any NodeRun exists FAILs the claimed Run as
  `consumption_error` while a Run that left records is never rewritten and a
  settlement error is logged, not raised; the executor refuses a non-positive
  timeout, a multi-node Run, and a Run that disappears before read-back;
  plain-dict node output persists as given; and `executable_by_consumer`
  rejects a CREATED Run offered directly.
- 1 in `tests/scheduling/test_admission.py`: `ScheduleRunAdmitter` admits the
  Run QUEUED in the same insert.

No tests were removed or moved.
