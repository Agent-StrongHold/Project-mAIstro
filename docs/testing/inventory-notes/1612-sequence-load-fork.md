---
inventory-delta:
  packages/maistro-core/tests: +20
---
# 1612-sequence-load-fork

Load and fork `GraphExecutionState` at a canonical event sequence (#1612) adds
twenty maistro-core test IDs, all in
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

Eight IDs were added in the CI-repair round for the same issue: the epoch
model's own hash invariants (blank or content-mismatched hashes are not
constructible); an epoch append whose continuation already carries the recorded
history returning the same object uncopied; a state matching a captured
`TraversalCheckpoint` linking its epoch to that fact and loading the checkpoint
evidence; `load_state` refusing a continuation whose canonical Run row is
missing; tampered epoch state content failing the hash re-derivation through a
store port that serves the corrupted document verbatim; a pruned
`TraversalCheckpoint` link failing closed; `fork_provenance` rejecting a blank
reason at the fact layer itself, past the store entry point; and eval-score
fields that are present but `None` contributing no revision to the fork fact.
The complexity refactor that accompanied them (per-epoch link verification and
fact slicing extracted into helpers, every function at radon rank B or better)
is pinned by the same suite: every error message and fail-closed order asserted
before the refactor is asserted after it.

No existing IDs were removed; every durable-runs behavior under test before
this change is still asserted by the same identity.
