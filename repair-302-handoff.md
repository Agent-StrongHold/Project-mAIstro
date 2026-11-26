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
