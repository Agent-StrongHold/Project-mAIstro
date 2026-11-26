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

## Second develop sync: #2306 collapsed the fork on develop's side (this round)

Develop advanced to `17746da75` and repaired the same hosted red from the
other direction: `#2306` collapsed `beartype` to a single unconditional
`0.23.1` in `uv.lock` (so `uv export` no longer emits two forks at all),
bumped the `security.yml` expected-member pin to `setuptools==84.2.1`, and
rewrote `parse_expected` back to flat pin sets (fork handling deleted as no
longer reachable) plus two new tests asserting the lenient any-branch rule
and the `one of X, Y (X or Y)` report clause.

Merge resolution (conflict in `scripts/check-image-lock-reconciliation.py`
only; every other overlapping file auto-merged coherently):

- The gate keeps this branch's superset: per-name pin lists, `@image-env@`
  interpreter capture, and the PEP 508 marker evaluator. It is strictly
  stronger than develop's flat-pin version and remains correct now that the
  lock no longer forks (single pins take the historical exact path; the fork
  machinery is dormant, not dead weight — the next fork re-arms it). The only
  develop-side change folded in is `_expected_clause`'s richer report
  (`one of X, Y (X or Y)`), which is compatible with both suites'
  substring assertions.
- `tests/test_check_image_lock_reconciliation.py` keeps every test from both
  sides (67 + 2 = 69; net node count unchanged vs develop's recorded
  baseline, hence `inventory-delta: +0`). Develop's
  `test_conditional_pin_with_multiple_marker_versions_accepts_either_branch`
  asserted develop's `2 marker-conditional pin(s)` OK-line phrasing; adapted
  (name and intent preserved, semantics identical — exit 0, lenient
  acceptance) to this gate's explicit fork-degradation phrasing
  (`no @image-env@ line — lenient`). Its companion unknown-branch test passes
  verbatim on the merged `_expected_clause`.
- `uv.lock`/`security.yml`/Dockerfiles/KNOWN-GAPS take the union: develop's
  beartype collapse + setuptools 84.2.1 + explicit `libbrotli1`, and this
  branch's digest bumps + worker docs.

Evidence (executed this round at the merged head):

- All four real exports (engine 130, hive 67, research 315, rsi-runner 220
  names): **zero forked names, zero `UnsupportedMarker`** — the hosted
  failure mode is doubly dead (gate understands forks; lock no longer forks).
- Real-docker proof on the merged gate: an image shipping the locked
  `beartype==0.23.1` on Python 3.13.16 reconciles (`OK … forks evaluated
  against the image interpreter's environment: yes`; this also proves the
  collapsed pin installs and imports on the images' interpreter), while a
  stale `0.22.9` image now fails with
  `version mismatch : beartype==0.22.9 (image) != beartype==0.23.1` — the
  gate still bites when the lock and an image diverge.
- `uv run pytest tests/test_check_image_lock_reconciliation.py` — 69 passed.
- `uv run pytest packages/maistro-canvas/tests` — 581 passed, 75 skipped.
- `ruff check .` / `ruff format --check .` — clean (3494 files).
- `uv run mypy --strict packages/maistro-core/src` — clean (827 files;
  CI's exact argv).
- Vulture ledger with CI's exact argv — exit 0, 0 unclassified (the merged
  ledger is develop's; the 1-row dormancy exists on develop's own checkout
  too, verified in a scratch worktree, not merge-created).
- Suite inventory: `tests/` 5916 == recorded; canvas 636 == recorded.
- `check-image-pins.py` (8 pins / 10 Dockerfiles, merged digest + libbrotli1
  present), `check-backlog-consistency.py`, canvas + hive-conductor frontend
  `npm audit --audit-level=high` — all clean.
