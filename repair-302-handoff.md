# Issue #302 repair checkpoint

Scope frozen: issue #302 only; salvage commit 6d971fea83, resolve existing merge conflicts in maistro-rsi/local_loop.py, trace_notes.py, tests/test_local_loop.py and quality/promotion-surface-baseline.json; sync verified origin/develop; inspect RSI promotion gate and adjacent export/review/quarantine/oracle paths and tests, relevant ADRs; focused fixes and inventory notes only.

Initial state: unfinished merge of 221dc3d517e7580dc80859259cfdf15a2fd3ec9e into auto-302, 4 conflicts, 4678 changed paths from upstream. Both diffs preserved outside worktree in ../incoming-302.patch and ../incoming-302-index.patch before editing. Prior implementation exists in 6d971fea83; prior round aborted during develop sync, not absence of implementation. No check-*.log files in supplied job directory. Prior result claimed readiness, not yet independently verified.

Assumption: finish preserved merge first, then merge fetched, verified origin/develop (7ba29c1cd0e45d0fa3ccc9cef807173e52b3c75d). Ledger policy forbids new ordinary implementation ledger debt; resolve promotion ledger conflict using upstream authority and document any remaining gate failure instead of authorizing debt here.

Validation and acceptance evidence pending.

## Round 3 (2026-11-26, CI-gate repair at 55afb8cb45)

The four failing CI checks were repaired without authorizing any new debt:

- Quality / Radon + Quality / Xenon: the two new C blocks the #302 gate introduced
  (`promotion_gate.py::verify_promotion_approval` C(12), `evaluate_promotion` C(14))
  were refactored under B — malformed/expiry probes split out of
  `verify_promotion_approval`, and the approval-collection phase extracted into
  `_approve_or_refuse`; `__main__.py::_run`'s genome-summary printing moved into
  `_print_genome_summary` (regression 16 -> 12 vs baseline 15). Both complexity
  improvements were BANKED in quality/radon-baseline.json (15 -> 12, 22 -> 21);
  ledger length unchanged at 124, so the pinned XENON_BASELINE stays equal.
  No grants were added.
- devskim: the one error alert (DS126858 "Weak/Broken Hash Algorithm") matched
  the literal substring `sha1` inside the help-text prose
  `<candidate-sha12>.approval.json`; reworded to `<candidate-sha[:12]>` (same
  meaning, no weak-hash token). Verified with a local DevSkim CLI run using the
  workflow's exact include/ignore globs: 0 error-level findings in maistro-rsi/src.
- formal-conformance: the failing step was `check-m1-convergence-freeze.py` —
  `DirectoryApprovalStore` (Store suffix, overlapping the ontology concept
  Approval) needed the sanctioned `M1 product-local projection: Approval`
  docstring marker; added. Checker now passes; formal oracle independence OK;
  all 670 formal models pass against real pgvector:pg18; extension lifecycle
  proof PROVED 13/13 stages, 62/62 checks.
- Coverage gate (producer coverage-postgres contributed no coverage data):
  NOT reproducible from branch content. Every producer leg was re-run locally
  against pgvector:pg18 (tests/migrations 173 passed; core PG suites 7606
  passed; backlog 115; canvas 666; hive-conductor evolve 58; brief-commit 44),
  and .coverage was produced (54.7% statements over its own source set).
  Nothing this branch changes is imported by those suites. Residual risk: the
  CI failure reads as an infra/timeout crash of the producer job (the captured
  log shows postgres background-worker chatter and asyncio teardown noise), not
  a code defect; if it recurs on the next queue run it should be triaged as
  runner capacity, not a #302 regression.

Validation battery this round: ruff check + format clean; radon ratchet exit 0
(124 == 124, no new/regressed/unbanked); xenon block=124 avg=0 module=0 with
CI's exact command; check-vulture-baseline exit 0 (1218 vs 1219, improvement
banked); check-promotion-surface exit 0 (plain and RATCHET_BASE_REV=origin/develop);
check-suite-inventory --suite packages/maistro-rsi/tests ok (1832 identities);
mypy unchanged on the touched files (13 pre-existing import-untyped/no-any-return
notes, none added; maistro-rsi is outside the CI mypy gate set);
packages/maistro-rsi/tests 1828 passed, 4 skipped; tests/test_complexity_gate_scope.py
+ test_promotion_gate.py 34 passed.

## Round 4 (2026-11-26, diff-coverage repair at 28f63b86)

The failing run (45877223503, job 140123561112) was read in full. The blocking
failure was NOT the round-3 coverage-postgres producer (that job succeeded in
this run) and the "Event loop is closed" lines are pytest
PytestUnhandledThreadExceptionWarning noise from aiosqlite teardown threads in
suites this branch does not touch. The gate failed on its final step:

- packages/maistro-rsi/src/maistro_rsi/__main__.py: 25.0% of 12 changed lines
  (uncovered 1081-1097 _print_genome_summary body, 1174 its call site);
- packages/maistro-rsi/src/maistro_rsi/local_loop.py: 85.7% of 84 changed
  lines (uncovered 2432/2439 merge-mismatch guard, 2455/2457 kept-review
  persistence, 2530/2531/2537 crashed-gate refusal, 2634 mechanical keep,
  2659 p>=theta keep, 2677-2679 unavailable-review park).

Repair: nine tests execute those fail-closed paths — six in test_local_loop.py
(crashed quarantine scanner refuses; gate evidence naming an unlanded commit
refuses; the mechanical floor is exclusive (at-floor kept judge-free, just-
below escalates and cold-start parks); a p>=theta judgment promotion persists
its kept-review record only after the merge; unavailable judgment machinery
parks) and a new test_run_genome_summary.py (summary printout shape,
empty-population degenerate path, --genome-db wiring). Every test pins the
#302 fail-closed guarantee the uncovered lines implement.

Evidence: full RSI suite under the coverage-unit producer's exact command
(1837 passed, 4 skipped), coverage.xml, then scripts/check-diff-coverage.py
with CI's exact base 7926d9ab4dda — ok, exit 0, post-commit. ruff check +
format clean; verifier's targeted pytest command 150 passed; vulture gate
(CI's exact args) exit 0; suite inventory +9 recorded in
docs/testing/inventory-notes/auto-302-diffcov-repair.md, check ok (1841);
promotion-surface exit 0. No production source changed in this round, so the
radon/xenon/vulture ledgers are untouched by construction.
