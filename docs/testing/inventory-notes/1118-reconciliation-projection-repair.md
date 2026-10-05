---
inventory-delta:
  packages/maistro-core/tests: +8
---

# Replaying reconciliation repairs a partially persisted settlement

A durable Invocation settlement can commit before its quota projection fails.
The public operator/provider reconciliation entry points now repair quota and
completion-hook evidence before returning an already-terminal record. Completed admission-claim replays
and stale terminalization winners use that same repair path. The
Invocation, its revision and its audit history remain unchanged; there is no
new physical provider call. Concurrent settlement winners follow the same
repair path.

Eight SQLite cases inject failure after the lifecycle commit and recover through
both public service entry points for APPLIED and NOT_APPLIED, plus concurrent
settlement winners during provider lookup and the final compare-and-swap write,
completed admission claims and a delayed worker terminalization. They assert hold
release, correct spend, one history entry and no redispatch. These tests fail
against the preceding bridge-only implementation, whose early return reported
success while the reservation was still held.
