---
inventory-delta:
  packages/maistro-core/tests: +21
---
# Settle a pre-launch Attempt after a terminal Run fence (#1085)

Control-plane caller review reproduced cancellation after `create_attempt`
persisted its leased CREATED row but before the service's logical preparation
and physical-owner registration. A terminal Run correctly refused preparation,
but the Attempt remained CREATED despite the completed cancellation fence.

The existing AttemptExecutionService now settles that same record as CANCELLED
with its original fencing token when a fresh read proves the parent Run is
terminal. It preserves an existing physical winner and never invokes Runtime.
It does not add a caller-side physical lifecycle writer, fabricate a lease, or
run generic logical reconciliation against incompletely prepared Nodes.

A nonterminal or unreadable Run is not evidence to abandon recovery. Those
preparation failures retain the existing CREATED Attempt and expiring lease;
the original error propagates. A failed terminal write remains an observable
failure and does not fabricate a persisted cancellation.

Seven cases use the shared memory/SQLite/PostgreSQL spine (21 collected):
terminal-fence race, nonterminal preparation failure with actual lease reclaim,
unfenced preparation cancellation, existing physical winner, two unreadable
fence reads, and terminal-write failure. Local memory and SQLite legs execute;
PostgreSQL legs require the repository's configured CI service. The terminal
Run-fence regression fails against the actual pre-fix service on both local
stores. No live Provider or full local Hive suite is involved.
