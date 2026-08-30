---
inventory-delta:
  packages/maistro-core/tests: +39
---
# claude-issue-641-resume-parked-schedule-runs-db21

Thirty-nine added, one **rewritten**, none removed — twenty-seven for the
change itself, six from a second Codex round, and six for the store-protocol
change that round required. The last two groups are described at the end. All in
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

Eight of the twenty came from the diff-coverage gate, and one of them found a
defect rather than an uncovered line. `_settle_unstarted_consumption` declines
to act when a NodeRun exists — and on a resume path one always does, that being
the premise — so a resume that failed before creating an Attempt left the Run
claimed RUNNING over a NodeRun that was still parked. That is the same
"claimed, with nothing running" state that helper exists to prevent, one
variant across. The tick now re-parks instead, and
`test_a_resume_that_fails_outright_leaves_the_run_parked` is that case.

The other seven are `resumable_pause`'s refusals, tested directly rather than
through the tick: each is a durable row the tick would have to be handed, and
building seven parked Runs to reach seven guards would test the fixture rather
than the rule.

Three more came from the diff-coverage gate on CI, which reached lines my local
run did not: the lost claim and both halves of the way back. The concurrency
test above can pass by the "second tick saw nothing parked" route without ever
exercising the claim failing, so that path is now forced rather than raced —
the transition table refusing is the same fact, deterministically.

The middle one is worth its own line. `prepare_execution` un-parks the NodeRun
before the executor runs, so a resume that fails *after* that leaves a NodeRun
genuinely RUNNING, and re-parking the Run over it would say the work stopped
when it had not. The guard that declines there was written on that reasoning
and now has the test that holds it.

Four more, and one correction, from a Codex review that found three defects.

The rewritten one matters most. `test_a_node_run_that_actually_started_is_not_re_parked`
asserted that a RUNNING NodeRun means the tick should stand back — the derived
state being the answer. That is true only when an Attempt is actually live.
`prepare_execution` un-parks the NodeRun *before* creating the Attempt, so a
failure in between leaves a RUNNING NodeRun with nothing under it, invisible to
both ticks: this one looks for parked Runs, recovery looks for Attempts, and
there are none. My test had blessed a Run that stays RUNNING forever. It is now
two tests, split on the fact that actually decides: whether an Attempt is live.

Two cover the starvation. The backlog is the steady state, not an edge case —
every Run parked by a failed Attempt sits WAITING until somebody takes the
retry decision, and `list_by_status` is oldest-first, so a scan bounded by the
*work* limit inspected the same ineligible rows every tick and never reached a
resumable Run. One test puts a live poll behind four failures with `limit=1`;
the other pins that the work limit still bounds a tick, since a scan that wide
must not become an unbounded amount of work.

The last covers multi-node Runs. `unresolvable_reason` answers `None` for them
deliberately — they are owed to the durable Graph traversal, not unrunnable —
so one parked at its first pause has exactly one NodeRun and passed every other
check. The tick claimed it, `_single_node` raised, and the warning repeated
forever without the graph advancing.

## The six from the second review round

Three findings, three fixes, two cases each — because in every pair the first
case is the one that looked sufficient and was not.

- **Rotating scan.** One proves a Run behind a full scan page is reached on a
  later tick; the second proves the cursor *wraps*, so advancing does not
  starve the front of the list instead of the back — the same defect facing the
  other way.
- **A `CREATED` Attempt is not something running.** One proves it no longer
  holds the Run claimed; the second proves a genuinely `RUNNING` Attempt still
  is left to the recovery tick, so the fix is not simply "always re-park".
- **Re-read the pause after the claim.** The first makes the re-read answer
  `None` and asserts the Run is not resumed — and it passes *with the fix
  reverted*, because it never reaches the line that chooses between the two
  pauses. The second asserts by identity which object the executor was handed,
  and is the only one of the six that catches that third fix.

Confirmed by mutation: reverting each fix fails exactly the case that names it.

## Six more, for `list_by_status`'s new `offset`

The rotating scan needed `offset` across the `RunStore` protocol and all three
backends, and the diff-coverage gate caught the guard clause bare in every one
of them. `test_consumption.py` gains one case on the existing `spine` fixture,
parametrized over two statuses and three backends: `offset` walks pages in
order, past the end is empty rather than an error, and a negative offset
raises.

Matched on the message rather than the exception type. `limit` raises
`ValueError` from the same method, so a bare catch passes whichever guard
fired — and the two are not interchangeable here. Refused rather than clamped
because SQLite reads a negative `OFFSET` as no offset at all while PostgreSQL
raises: leaving it to the backend would make one call mean two different
things, and the caller is a cursor, where silently starting from the beginning
again is precisely the bug the offset was added to prevent.
