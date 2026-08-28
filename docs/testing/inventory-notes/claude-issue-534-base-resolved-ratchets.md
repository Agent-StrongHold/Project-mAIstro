---
inventory-delta:
  tests/: +38
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

A further 14 were added after CI's diff-coverage gate failed this branch --
`scripts/` is in that gate's scope (#257), and it was right about a real hole
rather than a formatting quibble. `load_authorizations` had no tests at all: I
added it to the resolver after writing the test file and never came back. Eight node IDs
now cover it (the missing-field case is parametrised over the three fields) (absent file, a complete grant, each of the three missing fields,
another ratchet's entries not leaking, an empty section, an unparseable file).
Two more cover resolver paths the fixtures never reached -- `RATCHET_BASE_REV`
being honored, and a ledger that `cat-file -e` finds but `git show` cannot read.
Four cover the seams every wiring-reads test substitutes away: `_entries_from`'s
guards against a base ledger of another shape, `_trusted_baseline` run for real
against whichever of its three states this checkout produces (`origin/develop`
absent, present and sharing history, or present and sharing none), and the
helper loader removing a half-executed module from `sys.modules` instead of
caching the wreck.

Two existing tests in that file were re-pointed at the new `_trusted_baseline`
seam rather than replaced — `main` now judges new debt against the base, so a
test that substitutes only the worktree ledger would be judged against the real
repository's and fail for reasons it never set up. No test was removed.
