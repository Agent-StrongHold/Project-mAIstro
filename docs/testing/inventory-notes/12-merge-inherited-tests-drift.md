# Inherited `tests/` suite drift absorbed at the #12 develop merge

**Superseded by the 2026-10-18 develop sync (52b0eaecb).** This note first
recorded a compensating `tests/: +1` when the branch last merged
`origin/develop` (2f56be40a): at that base the develop ledger undercounted by
one (`expected 5260, collected 5261`), so the note carried the inherited +1 to
make the merged tree's ledger true again.

The newer `origin/develop` (fad17a87) has since reconciled its own `tests/`
ledger. On the merged tree `expected == collected` (5627) *without* the
compensation, so the stale +1 now over-counts by one — the gate reports
`DRIFT tests/: expected 5628, collected 5627`. The front matter is therefore
removed: this branch still adds zero test nodes to `tests/`, and the note's
only effect was to offset a develop undercount that no longer exists.

Evidence (2026-10-18): `python scripts/check-suite-inventory.py` reports
`expected 5628, collected 5627` before this edit and `ok tests/: 5627` after.
The extra develop note(s) that landed between 2f56be40a and fad17a87 fold the
historical +1 into develop's own sum, so auto-12 no longer carries it.
