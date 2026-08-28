---
inventory-delta:
  packages/maistro-core/tests: +36
---
# claude-m1-44-store-convergence

Durable graph execution stops keeping its own copy of the execution spine and
takes Run, NodeRun and Attempt from the canonical store (#44,
ADR-082826-d9f5). Three suites.

**`tests/graph/durable_runs/test_canonical_identity.py` (+14)** — the identity
and the lifecycle are the store's:

- a Run the durable graph executed is findable in the canonical store, in its
  own scope — the symptom #44 exists to remove;
- the Run is *adopted*, not created, so what admission recorded on it — actor,
  provenance — is what the execution reports;
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
  including for a pinned run_id and on resume of a pre-convergence record;
- and the traversal entrypoint takes the same path as the Attempt one, so which
  module a caller imported does not decide whether its Run exists.

**`tests/graph/durable_runs/test_canonical_recovery_contract.py` (+6)** — the
crash and retry seams that matter once `RunStore` is the sole system of record:
a pinned Run rejects a different Graph before any physical work; the canonical
parent is RUNNING before any node executes; traversal refuses to bootstrap a
Run of its own, so no orphan survives a failed first checkpoint; retry adopts
the NodeRun and the Attempt a failed checkpoint left behind rather than minting
a second physical identity; and one Run's lapsed lease is settled canonically
in place, so its immediate retry is admissible without waiting for a global
sweep.

**`tests/graph/durable_runs/test_canonical_execution_store.py` (+12)** — the
Attempt boundary after the delegation. Creation happens once, in the store;
the second-active-Attempt and terminal-NodeRun guards still refuse; lease
renewal goes to the store that holds the lease; and an Attempt this aggregate
never saw is reported as the disagreement it is rather than mirrored in.

Then the edges of adoption and scoped reclaim, which are where getting it
wrong is expensive rather than untidy: an unmirrored Attempt from a different
request, or one that already settled, or two of them at once, are all refused
rather than adopted — adoption repairs a single lost mirror write and nothing
else. A holder that renewed between the projection and the sweep has its live
work left alone and the stale projection repaired instead. An Attempt another
recovery already settled is reported, not rewritten. And losing the settle
race reports the winner rather than raising, because two recoveries observing
one lapse is a normal event.

**`tests/runs/test_lifecycle.py` (+4)** for `transition_path`: nothing to do,
one legal edge, a walked multi-hop gap, and a refusal to invent an exit from a
terminal status — silence there would hide a real disagreement about work that
is already finished.
