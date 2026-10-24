---
inventory-delta:
  tests/: +0
---

# Merge resolution: #93 marker-aware forks × #1182 split resolutions

Both branches fixed the same hosted false red (`Container scan + SBOM + cosign`,
"Reconcile installed packages to uv.lock":
`version mismatch : beartype==0.22.9 (image) != beartype==0.23.1`) from two
sides, and develop's #1182 commit rewrote the same gate script the #93 branch
had rewritten. The develop sync of f956a8142 into auto-93 therefore conflicted
on `scripts/check-image-lock-reconciliation.py`, and git's text auto-merge of
`tests/test_check_image_lock_reconciliation.py` produced an incoherent union:
the #1182 tests called `parse_expected` with develop's
`(required, conditional)` tuple API while the tree kept the branch's
`dict[name, list[LockedPin]]` API (67 collected, `SyntaxError` at import of the
then-unresolved script; after resolution: 1 failed / 66 errors until adapted).

## Resolution

`scripts/check-image-lock-reconciliation.py` keeps the #93 side (the
superset): per-name pin lists, the `@image-env@` interpreter-environment
capture, and the stdlib PEP 508 marker evaluator that judges each fork's
marker against the image's real interpreter — strict when the environment is
visible, lenient (any locked fork version accepted) when it is not. The #1182
side's reporting contract is merged in: `_expected_clause` renders a
lenient-fork mismatch as the full accepted set
(`one of beartype==0.22.9, beartype==0.23.1`) while single pins and
environment-selected forks keep their historical exact/marker-annotated
formats.

`tests/test_check_image_lock_reconciliation.py` keeps every test from both
sides (net node count unchanged, hence the +0 delta). The two #1182 tests that
assumed the tuple API were adapted to the merged one, preserving their names
and assertions' intent:

- `test_parse_expected_keeps_every_version_of_a_split_resolution` now asserts
  the parse-level fork list AND the three-way classification
  (`_classify_expected` puts the split name in `forked`, not
  `required`/`conditional`).
- `test_split_resolution_reconciles_with_whichever_branch_the_image_resolved`
  keeps its parametrized both-forks-pass through `main()` (no `@image-env@`
  line → lenient rule) and asserts the branch's lenient OK marker instead of
  the tuple-API conditional count.

The other two #1182 tests pass verbatim once `_expected_clause` is ported.

## Evidence

- `uv run pytest tests/test_check_image_lock_reconciliation.py` — 67 passed.
- Real-docker reproduction against real `uv export` fork lines with a Python
  3.13.16 interpreter fixture: resolved script green on the `< '3.15'` fork
  (`forks evaluated against the image interpreter's environment: yes`), red on
  the `>= '3.15'` fork with the applicable fork's marker named, and the
  pre-fix (461fb86b1) script reproduces the hosted red
  `beartype==0.22.9 (image) != beartype==0.23.1` byte-identical.
- `check-suite-inventory.py --suite tests/` and `--suite
  packages/maistro-canvas/tests` — ok (the union count still matches
  baseline + Σ deltas, both prior notes' rows still true).
