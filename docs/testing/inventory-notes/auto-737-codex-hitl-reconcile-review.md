---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #737 review: fair settlement repair, idempotent ticks, honest expiry paging

Four behavioral cases in `graph/durable_runs/test_hitl_settlement.py`:

- settlement residue (PAUSED canonical Run, TIMED_OUT continuation) is
  repaired with a budget of one even when a consistent terminal row fills the
  per-status prefix, because residue is found from the canonical PAUSED side;
- two reconcile ticks racing on the same residue settle it once; the loser's
  refused terminal hop is recognised as the same repair;
- the expiry tick repairs a continuation parked PAUSED whose canonical Run was
  never mirrored out of RUNNING, then settles it;
- the expiry tick pages past a stale candidate it cannot repair instead of
  re-reading it forever.

The existing crash-repair test additionally asserts the repaired Run and
NodeRun carry the recorded settlement time, not the reconciliation time.
