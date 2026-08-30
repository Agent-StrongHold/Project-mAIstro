---
inventory-delta:
  tests/: +19
---
# claude-issue-662-review-findings-0a88

Sixteen added, none removed, none rewritten, all in
`tests/test_ac_state_authorized_floor.py` — plus three call-site edits in
`tests/test_ac_state_merge_guard.py`, which change no count.

Every one of them exists because a Codex review on #663 found four defects,
three P1, in the mechanism that PR merged. They are grouped by the finding they
answer rather than by the function they touch.

`TestTheMergeGroupHonoursTheSameGrant` (6) covers both layers of the merge-group
bug. Three pure-comparison cases prove the grant matters: with the grant, without
it, and with a fall deeper than the grant names. Three caller-level cases drive
`_guard_actual_base()` itself so the merge path is covered too: a base grant is
resolved and permits the named fall, a deeper fall reports the applied floor,
and invalid base-grant provenance fails closed instead of being ignored.

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

Three more, and a note about how they came to exist. The diff-coverage gate
found `_guard_actual_base` — the function the merge queue actually runs — with
**no tests at all**, which is exactly how the grant came to be missing from it:
every test aimed at the note comparisons, and this path reads its measurements
off disk and asks `authorized_floors` itself, so testing the comparison in
isolation would have left that call unwritten and still passed. It did.

Two people fixed that at once. The stubbed cases above monkeypatch
`authorized_floors`, which is the right shape for asserting *that* the guard
consults it and *what* it prints when it refuses. These three cover what a stub
cannot: that the real call resolves a real base revision and finds a real
committed grant (or finds none, which is the ordinary state and must still
refuse), and that an unreadable report refuses before any comparison — a
missing measurement must not read as "nothing moved".
