---
inventory-delta:
  packages/maistro-core/tests: +14
---
# claude-issue-545-schedule-node-fidelity-cb03

Two new files, fourteen tests, nothing moved or deleted.

`test_consumption_node_fidelity.py` holds the four ways the schedule consumer's
node invocation differed from the durable graph executor's (#545). Two tests for
AC-1 (a node configured through `parameters` receives them; precedence is
`parameters` < `inputs` < schedule payload), one for AC-2 (the wired resolver
builds the dependency-injected kinds and hands them the Container's RunStore),
two for AC-3 (a human pause reaches PAUSED with its prompt and resume time; a
non-human pause parks WAITING) and one for AC-4 (the node sees its own
`node_run_id` and `attempt_id`).

Every one was verified by mutation rather than by inspection. Reverting each fix
in turn fails exactly the criterion that claims it, and the AC-3 pair
discriminates: collapsing the human pause onto WAITING fails one test and leaves
its sibling passing, which is the property that makes the distinction tested
rather than merely present.

The AC-2 test asserts on the resolver seam rather than on a delegation's
observable behaviour, deliberately. What the defect changed is *which
constructor runs*, and a bare-built node is indistinguishable from a wired one
until it reaches for a dependency it was never given; asserting on a successful
delegation would need a live peer and could still pass for the wrong reason.

`test_yield_disposition_edges.py` (+8) covers the yield path's edges, added
after the diff-coverage gate caught them: `execution.py` at 62.5% of its
changed branch arcs and `reconciliation.py` at 86.7% of its changed lines.
Both gaps are branches the consumer's own tests cannot reach — evidence that
is not a mapping, and a NodeRun already parked or never running — so they get
direct tests rather than coverage borrowed from the paths above them. The
already-settled case is parametrised over all four settled statuses, and its
fixture sets `finished_at` because the model refuses a terminal NodeRun
without one; a fixture the store could not really hold would prove nothing.
