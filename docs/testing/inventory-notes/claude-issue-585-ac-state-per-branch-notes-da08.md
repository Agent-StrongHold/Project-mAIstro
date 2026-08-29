---
inventory-delta:
  tests/: +36
---
# claude-issue-585-ac-state-per-branch-notes-da08

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_ac_state_notes.py` — 35 tests for SPEC-082926-25a2 (#585).

Thirty-one test functions; one is parametrised over eight malformed-note shapes,
which is why the node count is higher.

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
