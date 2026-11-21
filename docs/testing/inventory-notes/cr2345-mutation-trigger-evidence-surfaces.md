---
inventory-delta:
  tests/: +4
---

# Mutation trigger covers evidence-only PR surfaces (#2345 repair)

A PR whose diff touches exactly a governance/evidence surface never started
`mutation.yml`, so its required "Mutation gate (changed critical lines)"
check-run never appeared on the candidate head and `gates-ran` stayed pending
forever. Measured on #2345's head `720aaa2500` with the CI-exact evaluator
(`check-gates-ran.py --require-complete --base-branch develop --event-name
pull_request --changed-files <envelope>`): 71/72 required checks present,
"Mutation gate (changed critical lines)" absent -> exit 2 (PENDING). The
repair adds `requirements-dev-tools.txt` and `REPAIR-NOTES-*.md` to the
workflow's `pull_request.paths` (the same failure mode #2120 fixed for image
pins and #2371 fixed for grant ledgers / inventory notes).

Four node IDs in `tests/test_mutation_targets.py`, no removals or renames:

- a dev-tools bump PR (`requirements-dev-tools.txt`) matches the declared
  paths and triggers the gate;
- a root repair note (`REPAIR-NOTES-*.md` class, recurring across
  #1450/#1837/#2267/#2345/#2375/#2406) matches and triggers;
- every evidence surface a prior repair pinned (`quality/image-pins.json`,
  `quality/ratchet-authorizations.json`, `docs/testing/inventory-notes/**`,
  `.github/workflows/mutation.yml`, `packages/**/*.py`) remains a declared
  trigger — widening must not narrow; and
- an unrelated root doc change (`README.md`) still matches nothing (negative
  control: the widening is scoped, not a blanket trigger).
