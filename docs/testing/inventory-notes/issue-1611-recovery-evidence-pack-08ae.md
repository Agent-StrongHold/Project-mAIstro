---
inventory-delta:
  packages/maistro-core/tests: +6
---
# issue-1611-recovery-evidence-pack-08ae

#1611 adds `packages/maistro-core/tests/runs/test_recovery_evidence_pack.py`.
The six new node IDs are the evidence-pack contract itself: the ledger names
the five kill-recovery scenarios, a live-lease kill parks and emits a recovery
event, a stale fencing token is refused after reclaim, a replayed recovery
fact keeps one event id, a mixed-queue restart does not silently complete, and
a second reconcile does not rewrite Attempt history. No other suite moved, and
nothing was removed.
