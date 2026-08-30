---
inventory-delta:
  tests/: +13
---
# claude-issue-662-review-findings-0a88

Thirteen added, none removed, none rewritten, all in
`tests/test_ac_state_authorized_floor.py` — plus three call-site edits in
`tests/test_ac_state_merge_guard.py`, which change no count.

Every one of them exists because a Codex review on #663 found four defects,
three P1, in the mechanism that PR merged. They are grouped by the finding they
answer rather than by the function they touch.

`TestTheMergeGroupHonoursTheSameGrant` (3) is the largest. The grant reached
only the note comparisons, so an authorized fall passed everything on the
branch and was then rejected by the merge queue — the mechanism worked
everywhere except the one place it had to. The three cases are: with the grant,
without it, and with a fall deeper than the grant names. The middle one is the
control; without it the first would pass whether or not the grant did any work.

`TestAGrantMustSurviveTheChangeThatSpendsIt` (4) covers the matched pair about
which revision answers which question. Two prove a binding grant cannot be
spent and deleted in one change; two prove a *spent* one can be pruned, which
was impossible before — stale-ness read from the base failed every later run on
a grant the base still carried, including the run whose only change removed it.

`TestAMalformedSectionRefusesRatherThanCrashes` (4) and
`TestReadingTheCandidateFileAtAll` (2) cover the P2. A malformed section
crashed rather than refusing, which AC-6 promised, and `"ac-state": []` was
additionally read as "no grants" by the helper's own `or {}` — a file somebody
wrote and expected to be enforced, silently ignored. The last two separate the
two ways of finding nothing: an absent file is no grants and must pass, an
unparseable one is a refusal.

The three edits in the merge-guard suite pass `NO_GRANTS` explicitly rather
than taking a default. That is the point of the change: a default of "no
grants" on `_actual_base_regressions` is exactly the silent answer that let the
merge-group comparison forget them in the first place.

The fixture gained a sentinel — `None` empties the grants file, `UNCHANGED`
leaves what the base committed. Collapsing those made "the candidate removed
the grant" inexpressible, which is why two of these four defects shipped with
no test.
