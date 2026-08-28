---
inventory-delta:
  packages/maistro-core/tests: +13
---
# claude-m1-251-run-consumer-68a0

Thirteen new node IDs for the canonical Run consumer (#251, ADR-082826-b601),
purely additive:

- 12 in `tests/runs/test_consumption.py`: the tick executes an admitted
  single-node schedule Run to COMPLETED with canonical NodeRun/Attempt records;
  CREATED/foreign-source/multi-node Runs are never claimed; failed work parks
  and is not silently retried; concurrent ticks execute once (the QUEUED→RUNNING
  transition is the claim); a drained backlog is a no-op; and
  `RunStore.list_by_status` conformance across memory/SQLite/PostgreSQL spines
  (6 parametrized IDs) plus the ungated reference-store AC pin.
- 1 in `tests/scheduling/test_admission.py`: `ScheduleRunAdmitter` admits the
  Run QUEUED in the same insert.

No tests were removed or moved.
