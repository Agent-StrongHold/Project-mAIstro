---
inventory-delta:
  tests/: +1
---
# 813 — the index gate's exact-name lookup branch is executed

Repair-round delta (this worktree). The local reproduction of the Coverage
gate (registry + scripts producers, `check-diff-coverage.py --base
0df275362`) failed on `scripts/check-adr-index.py` at 50.0% of 4 changed
lines: the recursive conversion of `_adr_path()` (#813) left its exact-name
fallback — `ADR-NNN.md` with no title suffix, lines 95–96 — never executed,
because every other test reaches the lookup through the suffix form.

Test added to `tests/test_check_adr_index.py` (this delta): a sandbox ADR is
renamed to exactly `ADR-019.md` inside a subdirectory, so the assertion
exercises both dimensions of the lookup at once — the exact-name fallback and
recursive discovery. It asserts `_adr_path("ADR-019")` resolves the nested
exact-named file and that `--add-missing` rebuilds the row end to end.

Mutation evidence: the test fails (a) against the pre-#813 non-recursive
`rglob -> glob` mutation of the script (no nested hit), and (b) against a
removed fallback (`return None` for the exact branch). Both mutations were
applied and reverted during this round.
