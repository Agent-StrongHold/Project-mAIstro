---
inventory-delta:
  tests/: +27
---
# claude-issue-662-authorized-floor-fall-1347

All twenty-seven are `tests/test_ac_state_authorized_floor.py`, the suite for
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

Thirteen more came from a Codex review that found four defects, three of them
P1, and every one of them real.

The largest is that the grant was applied only to the note comparisons.
`check-ac-state.py` measures the actual base revision in a merge group and
compares it independently, so an authorized fall passed everything on the
branch and was then rejected by the queue — the mechanism worked everywhere
except the one place it had to. `TestTheMergeGroupHonoursTheSameGrant` covers
that comparison with a grant, without one, and with a deeper fall than the
grant names.

The other two P1s are a matched pair about *which revision* answers *which
question*. Stale-ness read from the base made pruning unfollowable: once the
notes overtook a grant, every later run failed on it, including the run whose
only change removed it. Permission read from the candidate would reopen
self-approval. So permission stays at the base and bookkeeping moved to the
candidate — and a binding grant must survive the change that spends it, or the
fall lands with the owner, issue and reason deleted from the file.

The P2 is that a malformed section crashed rather than refused, which AC-6
promised. `"ac-state": []` was additionally read as "no grants" by the helper's
own `or {}`, so a file somebody wrote and expected to be enforced was silently
ignored — a quieter failure than the crash.

The fixture gained a sentinel: `None` empties the grants file, `UNCHANGED`
leaves what the base committed. Collapsing those made "the candidate removed
the grant" untestable, which is why two of these defects had no test.
