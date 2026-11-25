---
---

# 1836 develop-sync merge: image-lock fork tests unioned (L1836 repair round)

Resolving the preserved develop-sync conflict (merge of origin/develop
17746da7 into auto-1836) touched three files that both parents had evolved:
`Dockerfile.rsi-runner`, `scripts/check-image-lock-reconciliation.py`, and
`tests/test_check_image_lock_reconciliation.py`. Both parents had independently
fixed the per-name parser; the resolution keeps the branch's per-line
required/conditional split and provenance docstring, plus develop's cleaner
pieces that had already merged cleanly (the extended `_expected_clause`
`one of a, b (a or b)` and the correct `dict[str, str]` annotation in
`parse_actual`).

## tests/: no delta against the recorded inventory

The union keeps the branch's 4 fork tests (documented in
`1836-image-lock-reconcile-forks.md`) and adds develop's 2:

- `test_conditional_pin_with_multiple_marker_versions_accepts_either_branch`
- `test_conditional_pin_with_multiple_marker_versions_still_names_an_unknown_branch`

These overlap the branch's fork coverage but additionally pin the develop-side
`(a or b)` clause suffix; both pass against the resolved script (39/39 in the
file). No `inventory-delta` is recorded and none is needed: relative to the
branch's pre-merge head the suite is +2, but develop's landing already banked
the same +2 (see `issue-5-reconcile-multi-conditional-pins.md`), so the
recorded inventory (tests/ = 5886) already counts them — a delta here would
double-count and flip the gate to an expected 5888. `check-suite-inventory.py`
reports tests/ = 5886 matching at the merge head.

Discrimination evidence for the union is recorded in
`1836-image-lock-reconcile-forks.md` (§ Executed discrimination evidence):
5 of the 6 fork tests fail against the old single-pin parser, 2 of 6 against
the merge base's name-keyed-set parser, 0 against either fixed parser.
