---
inventory-delta:
  tests/: +9
---
# claude-issue-691-grant-is-not-a-cap-a962

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

All nine are added, none removed: `TestAGrantIsPermissionNotACap` in
`tests/test_ac_state_authorized_floor.py`, covering SPEC-082926-6f49 AC-9.

Seven drive the gate end to end on develop's own numbers — base fold 28.2327,
a landed grant at 27.8791, and a measurement placed above the fold, between the
grant and the fold, exactly on the grant, and below it. The two that measure
*above* the grant are the deadlock #691 names: both fail on `develop` and pass
here, and the between case is the one that catches most branches, since a grant
exists precisely because the inherited fold is too high.

The eighth reads `_fresh_note_bound` directly. It is the seam the fix turns on
— the inherited notes are what a grant corrects, the notes a change writes are
what "did you bank it?" asks about — and a unit test says which half is which
in a way the end-to-end runs cannot.

Nothing on `develop` was deleted. Two unit tests of `_floors_being_taken`, a
helper from this branch's own first and narrower attempt, were replaced by
behavioural tests of the mechanism that superseded it. That helper only ever
existed on this branch, so the +8 is measured against `develop` and the
replacement nets out inside it.

The ninth is a regression test for a hole the first version of this fix opened
(Codex, #692): building the exact target from the *base* bound rather than the
worktree fold stopped the run seeing an inherited note the change had rewritten
downward. It drives that shape — the sole note goes 20 to 15 while the
measurement stays 20 — and fails against that formulation, where the run
reported `OK` and the floor would have silently dropped after the merge.
