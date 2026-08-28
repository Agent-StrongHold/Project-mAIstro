---
inventory-delta:
  tests/: +24
---
# claude-issue-534-base-resolved-ratchets

Twenty-four new tests for the base-resolved ratchet baseline (#534, #319),
purely additive:

- 19 in `tests/test_ratchet_provenance.py` — the resolver itself, against real
  git repositories rather than a mocked `git`, because the plumbing *is* the
  thing under test: which commit a ledger is read from, that the merge base is
  used rather than the moving tip, that a ledger absent at the base tolerates
  nothing, and that an unresolvable base, an unreachable history, a corrupt
  ledger and a path outside the repo each fail instead of falling back to the
  candidate's copy. Plus the developer loop (no base available reads the
  worktree and says so) and the provenance record's required fields.
- 5 in `tests/test_check_wiring_reads.py::TestTheLedgerIsNotItsOwnOracle` — the
  reproduction from #534 pinned at the gate: weakening the metric, banking it
  with `--update`, and writing the justification, all in one tree, still fails;
  the verdict names the commit it judged against; an explicit authorization
  lets a deliberate floor-raise through; removing a tolerated entry needs no
  authorization; and an unreadable base fails rather than trusting the
  candidate.

Two existing tests in that file were re-pointed at the new `_trusted_baseline`
seam rather than replaced — `main` now judges new debt against the base, so a
test that substitutes only the worktree ledger would be judged against the real
repository's and fail for reasons it never set up. No test was removed.
