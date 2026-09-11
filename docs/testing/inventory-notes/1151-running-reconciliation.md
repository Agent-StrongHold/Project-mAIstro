---
inventory-delta:
  packages/maistro-core/tests/graph/durable_runs: +7
---
# 1151 running-run reconciliation

Five tests in `tests/graph/durable_runs/test_canonical_durable_store.py` cover:

- terminal NodeRuns settling a canonical `RUNNING` Run without a new Attempt;
- a `RUNNING` continuation with `resume_at=None` becoming due;
- terminal `FAILED` continuation state settling a stranded canonical Run;
- stale continuation status being repaired from a terminal canonical Run;
- a missing continuation remaining absent rather than violating the checkpoint authority ADR;
- the checkpoint-1 `QUEUED` continuation / canonical `RUNNING` window;
- a transient physical Attempt completion write being retried without losing its result.
