---
inventory-delta:
  packages/maistro-core/tests: +22
---
# claude-m1-44-store-convergence

Durable graph execution stops keeping its own copy of the execution spine and
takes Run, NodeRun and Attempt from the canonical store (#44,
ADR-082826-d9f5). Three suites, all additive.

**`tests/graph/durable_runs/test_canonical_identity.py` (+12)** — the identity
and the lifecycle are the store's:

- a Run the durable graph executed is findable in the canonical store, with its
  scope and `executor` provenance — the symptom #44 exists to remove;
- the identity is the store's, so the record's `run` is a projection of a row
  that already exists rather than an id minted first and persisted after;
- the frontier's NodeRuns and their Attempts are findable there too, with the
  same ids the record carries;
- a settled Attempt does not read differently depending on which store is
  asked, which is what identity without lifecycle would have produced;
- the Run and its node reach their terminal status canonically, on success and
  on failure alike — a Run left RUNNING because its graph failed is work
  nothing will recover, since recovery only looks at what the store calls open;
- a node answered out of a HITL pause reaches COMPLETED through QUEUED and
  RUNNING, because PAUSED to COMPLETED is not an edge the lifecycle table has;
- without a `run_store` nothing reaches the spine and behaviour is unchanged,
  including on resume of a record written before the convergence;
- a pinned `run_id` still wins, because an already-admitted Run being executed
  must not be given a second identity.

**`tests/graph/durable_runs/test_canonical_execution_store.py` (+6)** — the
Attempt boundary after the delegation: creation happens once, in the store;
the second-active-Attempt and terminal-NodeRun guards still refuse; lease
renewal goes to the store that holds the lease; and an Attempt this aggregate
never saw is reported as the disagreement it is rather than mirrored in.

**`tests/runs/test_lifecycle.py` (+4)** for `transition_path`: nothing to do,
one legal edge, a walked multi-hop gap, and a refusal to invent an exit from a
terminal status — silence there would hide a real disagreement about work that
is already finished.
