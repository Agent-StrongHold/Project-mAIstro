---
inventory-delta:
  tests/: +14
---
# claude-issue-662-authorized-floor-fall-1347

All fourteen are `tests/test_ac_state_authorized_floor.py`, the suite for
SPEC-082926-6f49: a grant read at the base revision may lower one AC-state
floor to one named value. Nothing removed or moved.

Twelve were the first push. Two more came from the diff-coverage gate, which
found three branch arcs the suite reached along one side only —
`_report_stale_grants` was only ever entered with nothing to report, and
`_lowered` was only ever handed a counter the fold already carried. Both are
real cases rather than arcs padded to satisfy a percentage: a spent grant has
to *fail* the run that finds it, not merely be printed under a passing one, and
a grant naming a counter no note measured must narrow nothing rather than
inventing the key.

They run against a real Git repository rather than a stubbed fold, for the
reason `test_check_ac_state_ratchet.py` records at length: a fixture that points
`ROOT` at a non-repository makes provenance fall back to the worktree, and the
base fold and the worktree fold then read the same notes — so a test meaning to
prove "read at the base" passes with the mechanism removed entirely. That is how
the #609 tests went quiet, and the case here that would go quiet first is
`test_a_grant_written_in_the_same_change_does_not_take_effect`, which is the
whole point of the feature. `test_the_harness_reads_grants_from_the_base` pins
the harness so that cannot happen silently.

Two of the twelve changed what the change itself claims.

`test_a_landed_grant_permits_the_fall_it_names` failed at first because the
grant lowered only the *regression* floor. The exact comparison folds the
worktree notes with `max` too, so a branch cannot record a lower value either —
its own note beside a higher `_baseline.json` folds to the higher one — and the
run demanded the number the correction had just disproved. Both comparisons take
the grant now.

That made the grant the record rather than a step toward one, which falsified
the criterion I had written next to it. AC-5 said "a grant does not excuse
banking"; the design does not enforce that and cannot, so the criterion now
states what is true and enforced — the authorized value is a target, not a
basement, and a measurement above it is slack to bank rather than a pass.
`test_a_measurement_above_the_grant_is_slack_to_bank` is that criterion.
