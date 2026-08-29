---
inventory-delta:
  packages/maistro-core/tests: +12
---
# claude-issue-641-resume-parked-schedule-runs-db21

Twelve added, none removed, none rewritten. All in
`tests/runs/test_parked_run_resume.py`, the suite for SPEC-082926-a44e.

Three of the twelve pin the classification table itself, and six exercise the
tick end to end against Runs that were parked by *running* the consumer rather
than by writing a parked row — a hand-made NodeRun and Attempt would let the
suite agree with itself about what a pause looks like while disagreeing with
the code that writes one.

The load-bearing fixture is `_DispatchingPauseNode`, which counts how many
times it takes its dispatch branch. Every other case here could be satisfied by
a tick that resumed nothing at all; only a counter separates "correctly
refused" from "did nothing". Reclassifying `awaiting_remote_delegation` as
elapsed fails exactly that test and its table sibling, and leaves the other ten
passing — which is the check that the classification is doing the work rather
than decorating it.

The last one is a unit test on `jira.wait_for_subtasks`, not on the tick: it
proves the node can now reach its own recorded deadline. It could not before,
on any path — `wait_first_seen:<node_id>` was read and never written by
anything but tests, so the node took its first-reach branch every time. Latent
while nothing resumed; an unbounded poll the moment something does, which is
why it is fixed here rather than filed.
