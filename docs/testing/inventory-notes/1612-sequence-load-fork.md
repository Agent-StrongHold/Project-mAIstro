---
inventory-delta:
  packages/maistro-core/tests: +12
---
# 1612-sequence-load-fork

Load and fork `GraphExecutionState` at a canonical event sequence (#1612) adds
twelve maistro-core test IDs, all in
`packages/maistro-core/tests/graph/durable_runs/test_time_travel.py`.

The new durable state timeline records one full `GraphExecutionState` epoch per
distinct persisted state at the `CanonicalDurableRunStore` persistence
boundary, so a sequence position can be loaded without reconstructing content
that commits and checkpoints only carry as hashes. The tests cover the contract
end to end: epoch-one launch state and per-advance appends; first, interior and
terminal positions with the inclusive event slice; out-of-range and
legacy-empty-timeline refusals; unknown runs; read-only determinism of a
repeated load; pruned-commit and foreign-Graph-revision evidence failing
closed; the park → load → fork acceptance proof across real SQLite store
reopens with both lineages inspectable and the source Run untouched; fork
inheriting state as data without re-executing completed work; the stale-writer
fence; fork provenance recording parent, source position, reason and the
relevant Goal/Rubric revisions; and timeline-position stability when unchanged
state is written twice.

No existing IDs were removed; every durable-runs behavior under test before
this change is still asserted by the same identity.
