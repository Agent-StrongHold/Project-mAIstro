---
inventory-delta:
  packages/maistro-core/tests: +33
---
# claude-issue-545-schedule-node-fidelity-cb03

Three new files, thirty-three tests, nothing moved or deleted.

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

`test_human_pause_reasons.py` (+19) arrived from a Codex review that found the
two readers of a pause reason each naming two of the four reasons production
nodes actually raise. Four tests pin what the readers now decide (every human
reason on both paths, every system reason on neither, absent metadata on
neither), two pin the Run inheriting its NodeRun's parked state (AC-6), and the
rest hold the sets themselves.

The load-bearing one is structural: it walks the node package's AST for
`pause_until` calls and fails when a node pauses for a reason the declared set
does not name. A test that merely listed today's reasons would pass again the
moment a fifth was added and forgotten, which is precisely the failure it
exists to catch — the previous allowlists were wrong for as long as they were,
because nothing failed while they were.

It was checked by counterfactual, not by inspection: swapping one node's
constant back to a bare literal fails it, and restoring the constant passes it.
It also earned its keep on first run, flagging three reasons the set it was
written against did not have (`awaiting_remote_delegation`, `awaiting_harness`,
`waiting_on_jira_subtasks`). Those turned out to be system waits, so WAITING
was already the right answer for them — but nothing had established that, which
is why they are now declared as `SYSTEM_PAUSE_REASONS` rather than left to
arrive at WAITING by default.

Two findings from the same review are filed rather than fixed here: #641 (a
yielded schedule Run has no resume path, and requeueing it repeats a dispatch)
and #642 (a successful pause increments `executions_failed`). Both are named in
the spec so a reader meets them there rather than in the code.
