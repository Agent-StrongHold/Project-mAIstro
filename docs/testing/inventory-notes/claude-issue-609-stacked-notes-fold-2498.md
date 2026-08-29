---
inventory-delta:
  tests/: +7
---
# claude-issue-609-stacked-notes-fold-2498

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Thirteen tests for the new rule, six removed with the old one — hence +7, which
is the number this note exists to explain.

`tests/test_ac_state_notes.py`'s AC-7 block was **rewritten, not extended**. Its
six tests were about identifying *one* note: found on a detached head, found
after a rename, absent when nothing was banked, absent when only the baseline
moved, absent when two notes changed, absent when the note was already at the
base. Three of those claims survive in the fold and are kept in the new shape
(detached head, rename, no notes at all). The other three were assertions about
the rule #609 removes — "two changed notes means none" is the defect — and
leaving them would have left the suite asserting the bug.

Eight new ones there: the stacked pair that used to fail, the three surviving
claims restated over the fold, the baseline now counting toward the claim
(the old rule excluded it), a weak note not lowering the claim, and the
deletion that still cannot reach the regression bound because that one is
folded at the base, and a notes directory that does not exist at all (a branch
cut before the scheme), which the diff-coverage gate asked for.

Five in `tests/test_check_ac_state_ratchet.py`, at the gate rather than the
helper, because the failure this fixes was a gate failure: a stack that banked
passes, a stack that measured above every note is still told to bank, banking
below what was measured is still refused (#609's AC-4, the single-note case that
already worked), a weak note beside a strong one buys no slack, and a regression
is still refused. Those five are the mutation half — each is the fold's rule
under a change that would break it.
