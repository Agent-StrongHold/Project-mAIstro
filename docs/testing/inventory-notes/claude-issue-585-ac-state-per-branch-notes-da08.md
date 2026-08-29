---
inventory-delta:
  tests/: +61
---
# claude-issue-585-ac-state-per-branch-notes-da08

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_ac_state_notes.py` — 41 tests for SPEC-082926-25a2 (#585).

Thirty-seven test functions; one is parametrised over eight malformed-note
shapes, which is why the node count is higher.

The collision tests build **real repositories with real branches and really
merge them**, rather than asserting over a dictionary. "Two branches do not
conflict" is a claim about git, not about arithmetic, and the control test —
`test_the_shared_ceiling_file_would_have_conflicted` — writes the old shared
file on the same two branches and asserts the merge *does* fail. Without it,
"no conflict" could just mean the two branches wrote identical bytes.

Six existing tests changed rather than being added to, because #585 retired the
files they read:

- `test_check_ac_state_ratchet.py`'s `ceilings` fixture writes a note into a
  throwaway notes directory instead of a ceilings file. Its assertions are
  unchanged; the fixture name is kept so they still read the same.
- `test_the_shipped_ceilings_cover_every_ratcheted_counter` became
  `test_the_shipped_baseline_note_covers_every_ratcheted_counter`, and gained a
  sibling asserting every shipped note parses.
- `test_check_ac_state.py`'s `test_the_shipped_floor_is_the_measured_value` read
  a committed ceiling against a committed report. Neither is committed now, so
  it became `test_the_shipped_notes_agree_with_the_folded_floor`; the half it
  drops — floor equals measurement — is what `--ratchet` itself now asserts.
- `test_autonomous_merge_policy_inputs.py` names the surviving ledger.

Six more arrived after the first CI run on this branch failed for a reason the
design had not anticipated: CI checks out a detached head, so
`git rev-parse --abbrev-ref HEAD` answers `HEAD`, the note filename derived from
that name matched nothing, and the ratchet read a banked improvement as unbanked
and failed the branch that had banked it. `own_note` now finds the candidate's
note by what the change did — the one note it added or altered since the base —
so the name is no longer load-bearing. AC-7 is the criterion for that, and the
six cover the detached head, a renamed branch, a candidate that banked nothing,
one that only re-settled the shared baseline, one that touched two notes, and a
note already merged into the base.

Thirteen more came from the per-file diff-coverage gate, which found the whole
report-only half of the change untested: an unreadable note stopping the ratchet
and the mode guard rather than passing them, an empty fold naming the bank
command, `--show-bounds` over a full fold and over one that bounds a single
counter, `--compact` on a missing directory, an empty one, and one holding a
note it cannot parse, both commands reached through `main`, and a notes module
whose top level raises leaving nothing half-initialised in `sys.modules`.

`tests/test_ratchet_provenance.py` gained a `TestResolveBaselineDir` class — six
tests, the directory form's first direct coverage. Two of them delete a loose
git object to reach the failures the code discriminates between: losing the base
commit's tree makes `ls-tree` fail the way an absent directory does, and only the
`cat-file` probe tells "empty fold" from "unreadable oracle"; losing a blob alone
is the one state where the listing and the contents disagree. Both follow this
file's rule of building real repositories — a mocked `git show` would have agreed
with whatever the implementation did.

`RETIRED_CEILINGS.relative_to(ROOT)` in `load_notes` was replaced by a stored
relative path while writing these: it crashed for any caller that pointed `ROOT`
at a synthetic tree, which is every unit test of the fold.
