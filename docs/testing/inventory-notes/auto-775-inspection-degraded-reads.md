---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# auto-775-inspection-degraded-reads — degraded durable-read coverage (#775 repair)

Three new collected cases in
`packages/hive-conductor/backend/tests/test_dag_run_creative_inspection.py`
covering the degraded-read paths of the #775 creative inspection that the
happy-path and spine-less cases never reach, closing the diff-coverage gate
failure on `services/dag_run_inspection.py` (88% of changed lines < 90%) and
`services/engine.py` (50% < 90%):

- A durable graph store whose read raises: the run-level creative block still
  answers and per-artifact reconstruction degrades to an empty list (the
  `except Exception` guard), never a failed read and never invented state.
- A durable store that answers `None` (run unknown to the spine): the same
  degraded empty-artifact answer.
- The `EngineService.graph_run_store` seam directly: `None` with no port
  bound, `None` with a container lacking the store, and exactly the
  container's store object when present — the `getattr`-default arcs.
