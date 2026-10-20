# Repair/verification notes — #796 (M7-A7 eval-consumer map)

Lane `auto-796`, branch head `1f8ea45fca2c37876093268c2ca27b11f989e8cf`,
develop merge-base `f72d4fc921135dfe7df727c226fa6a29903c59af`. This note records
the independent verification of the repair commit `1f8ea45fc` ("bank #779
consistency-evaluator identities in the design-surface scan"), which resolved the
regression found in the previous round.

## What failed, and how it was resolved

The develop merge `d8a388bc2` brought `maistro_design/consistency.py` (#779
project-quality consistency evaluator) and the pack-upgrade preflight into the
tree after the M7-A7 contract test `88e3756ed` had landed. The def-name net in
`test_maistro_design_declares_no_scoring_or_promotion_surface` then flagged five
pre-existing definitions (prior-round evidence: job `a4e16c34…`,
`check-3.log` — `consistency.py:349,362,656,1039` + `packs/service.py:650`).
That failure is itself evidence the tripwire is live, not vacuous.

`1f8ea45fc` banked the five identities by exact `(relative_path, name)` in
`_DESIGN_SURFACE_BANK`
(`packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py:91`) and
kept the scan's strength: path-pinned rows, stale-row failure, and a negative
control proving a banked name at a different path still trips
(`test_tripwires_catch_the_forbidden_shapes`, impostor case at
`test_m7_a7_eval_consumer_map.py:531`).

## Banking review (the boundary judgment the previous round escalated)

Issue #796 lists #779 as **Related** and forbids exactly four shapes: an Evolve
fitness that invents a design-quality score for the same Goal; RSI mutating
Rubric/evaluator/fence policy; Design Studio calling Evolve/RSI as the in-Run
critic; a `maistro-design` private promotion path. None of the five banked
identities matches any of these:

- `consistency.py` pins its own contract in the module docstring:
  "Proposal, never mutation … no write path to any store"
  (`packages/maistro-design/src/maistro_design/consistency.py:19`), "deliberately
  deterministic … no model call" (`:10-11`), and "This is project-quality
  evaluation, not a self-improvement authority — historical evaluations may later
  become M4 evidence, but this module only evaluates and proposes for the current
  creative project" (`:35-38`). It is a *producer of evidence* — the map's
  consumer side — not a competing scoring authority.
- `evaluate_project_snapshot` (`consistency.py:1039`) is a pure function:
  "no store access, no mutation, no model calls" (`:1042`); it returns an
  in-memory `ConsistencyEvaluation` (verdict + findings + a proposal-only
  `RefinementProposal`), and stores nothing — so it cannot create a third home
  for a design-quality score either.
- `_evaluate_upgrade` (`packs/service.py:650`) is a read-only preflight returning
  `PackUpgradePreflight` with `can_upgrade=not blocked` (`:671`): it *blocks*
  upgrades on regressions/unauthorized backends/dropped rubric dimensions and
  promotes nothing. Promotion authority stays with #21.
- No banked identity imports `maistro_rsi`/`maistro_evolve` — tests 1-2 of the
  contract file pass, so none of them wires a second loop in.

Conclusion: banking these five is consistent with #796's forbidden list; the
module-name scan and the def-name net remain fully armed for anything else.

## Validation executed at `1f8ea45fc` (all green)

- `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -v` — 7/7 pass
  (including the previously failing surface test).
- `uv run pytest packages/maistro-core/tests/fitness/ -q` — 34/34 pass.
- `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -q` — 13/13 pass.
- `uv run pytest packages/maistro-design/tests -q` — 572 passed, 1 skipped.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run python scripts/check-convergence-matrix.py` — OK (52 subsystems / 1404 modules), exit 0.
- `uv run python scripts/check-suite-inventory.py` — ok (17 suites match), exit 0.
- `uv run python scripts/check-doc-links.py` — 0 broken links, exit 0.
- `uv run python scripts/check-contract-markers.py` — OK, exit 0.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) — exit 0, 1322 identities.
- `git merge-tree --write-tree HEAD origin/develop` — exit 0 (conflict-free); all
  five banked names still declared on `origin/develop` (develop's `d8675ac89`
  refactor kept them), so a future sync will not strand the bank.

## Residuals

- Acceptance criterion "PR is `feat/m7-a7-eval-consumer-map` off `develop`" is
  dispatcher-owned GitHub state; lane workers may not push or open PRs, so it is
  unverifiable locally by construction. The branch content itself is complete and
  green against the develop merge-base.
- The `(path, name)` bank is a documented boundary judgment. This note is the
  in-tree evidence dossier for that review; `_DESIGN_SURFACE_BANK`'s own
  docstring carries the same rationale at the point of use.

## Round 3 (2026-10-19, head `638aeb4b8`): the #2204 refactor split the bank's
target — re-bank `_evaluation_provenance`

The develop merge `638aeb4b8` (develop `5f714e1be`) brought `d8675ac89` (PR
#2204, the #1663 consistency-evaluator complexity refactor), which extracted the
inline `EvaluationProvenance(...)` construction out of the banked
`evaluate_project_snapshot` into a new pure helper, `_evaluation_provenance`
(`consistency.py:1086`). Verification job `cf690baf…` caught it:
`check-3.log` — `test_maistro_design_declares_no_scoring_or_promotion_surface`
failed with exactly one offender, `consistency.py:1086 def
_evaluation_provenance`.

Re-review against #796's forbidden list: the helper cites the exact
brief/decision/artifact revisions the read-only evaluation saw — the same
provenance record the already-banked `EvaluationProvenance` class models. It is
pure construction from the frozen snapshot (no store access, no mutation, no
model calls, no score, no promotion) and is called only from the banked
`evaluate_project_snapshot` (`consistency.py:1128`). Same exception class as the
rest of the bank; re-banked by exact `(path, name)` identity in the PR that
merged the move, as the bank's own stale-row contract requires. A full re-scan
of the package with the test's own scanner found no other offender, no module-
name offender and no stale bank row.

Validation this round: the M7-A7 contract file 7/7, the `fitness/` directory,
the M5 reachability suite, `maistro-design` tests, ruff check/format, and the
CI gates (`check-convergence-matrix.py`, `check-suite-inventory.py`,
`check-doc-links.py`, `check-contract-markers.py`, `check-vulture-baseline.py`
with CI's exact arguments) — see the commit message for per-command results.

## Round 4 (2026-10-20, head `2658c27c5`): the preserved `origin/develop` sync conflict, resolved

The round opened with a merge already in progress in the worktree: `origin/develop`
(`e20e9f52ea94`) merged into `auto-796` (`0cfd4579f19c`) with nine unmerged paths and
`MERGE_HEAD` still set. No implementation defect was open — the M7-A7 contract file was
green at the previous head — so this round's work was the conflict resolution plus a
full re-validation on the merged head.

### Why the nine paths conflicted

The merge base git picked for those paths was `c5e070d97d`, whose blobs still contain
upstream's committed `Temporary merge branch` conflict-marker lines. Both sides had
since cleaned those lines up differently, so every hunk overlapped and git could not
auto-merge.

### How it was resolved

- **Eight files** — `deploy/scripts/verify-restore.sh`,
  `docs/install/deployment-topology.md`,
  `packages/maistro-core/src/maistro/graph/durable_runs/attempt_executor.py`,
  `packages/maistro-core/src/maistro/persistence/pg_audit.py`,
  `packages/maistro-core/src/maistro/persistence/sqlite_audit.py`,
  `packages/maistro-core/src/maistro/security/sentinel/audit.py`,
  `packages/maistro-turing/backend/routes/chat.py`,
  `tests/cross_product_parity/harness.py` — were byte-identical on our side to
  `64ea662cb015` (an ancestor of develop's tip), i.e. **this branch had no change
  there**. Develop's tip version is the forward-evolved truth for those paths and was
  taken verbatim; nothing of ours was lost, because we had nothing there.
- **`docs/architecture/CONVERGENCE-MATRIX.md`** is the only path this branch had
  actually edited (the "One scoring loop…" section). Resolution = develop's newer
  document (its ownership census moved to 52/73/31) with our section re-inserted
  verbatim above `## Related`. `git diff --numstat e20e9f52ea94 HEAD --
  docs/architecture/CONVERGENCE-MATRIX.md` → 21 added lines, 0 removed: the section
  survives the merge unchanged and the census stays develop's.

Resolution commit `2658c27c5825` (`Merge commit 'e20e9f52ea94…' into auto-796`).
The branch's whole delta against develop is still the four issue surfaces:
`REPAIR-NOTES-796.md`, the matrix section, the inventory note and
`packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py`
(`git diff --numstat e20e9f52ea94 HEAD --stat` → 4 files, 751 insertions, 0 deletions);
`git diff --numstat e20e9f52ea94 HEAD -- 'packages/*/src'` is **empty**, so the merge
introduced no production-code delta.

### Ledger integrity through the merge

- The merged tree is byte-identical to `e20e9f52ea94` for `quality/`
  (`git diff --numstat e20e9f52ea94 HEAD -- quality/` is empty) — no per-identity ledger
  row was lost in the merge.
- The vulture ratchet re-bases on `merge-base(origin/develop, HEAD)`, which the merge
  moved from `64ea662cb015` to `e20e9f52ea94`. Re-run with CI's exact arguments:
  `1326 reviewed identities -> 1326 findings`, exit 0. Develop's five newly banked
  `admission_identity` rows are now the trusted baseline instead of "new debt" — the
  ledger needed no amendment from this branch.

### Re-validation on the merged head (`2658c27c5`)

- `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -q`
  → 7 passed.
- `uv run pytest packages/maistro-core/tests/fitness/ -q` → 34 passed.
- `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -q`
  → 13 passed (M5 invariant unchanged).
- `uv run pytest packages/maistro-design/tests -q` → 575 passed, 1 skipped.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 3363 files formatted.
- `uv run mypy <7 src trees>` → no issues in 906 source files.
- `scripts/check-convergence-matrix.py` → OK (52 subsystems / 1417 production modules);
  `scripts/check-suite-inventory.py` → ok (21 suites match);
  `scripts/check-doc-links.py` → 0 broken links; `scripts/check-contract-markers.py` → OK;
  `scripts/check-merge-markers.py` → ok; `scripts/check-vulture-baseline.py` → exit 0.

### The contract tripwires are live (out-of-tree proof, not just the in-file negative control)

The in-file negative control (`test_tripwires_catch_the_forbidden_shapes`) proves the
scanner helpers catch their shapes. To prove the *test functions* fail on a forbidden
tree, the contract file was copied outside the repo
(`/tmp/m7a7-demo/repo/packages/maistro-core/tests/fitness/test_demo.py`, so
`_REPO_ROOT` resolves to the synthetic tree) with two forbidden shapes planted:

- `maistro_design/engine.py` → `import maistro_evolve.cycle` +
  `from maistro_rsi.local_loop import LocalRsiLoop`;
- `maistro_design/stores.py` → `design_quality_score = 0.9`.

`uv run pytest <demo>/test_demo.py -k "design_loop_does_not_import_rsi_or_evolve or
no_design_quality_scores_stored_outside_the_canonical_homes"` → **2 failed**, with

- `AssertionError: Design Studio loop imports RSI/Evolve as a critic — a second loop
  (#796) … Offenders: ['packages/maistro-design/src/maistro_design/engine.py:1 import
  maistro_evolve.cycle', 'packages/maistro-design/src/maistro_design/engine.py:2 from
  maistro_rsi.local_loop']`;
- `AssertionError: Design-quality score stored outside Run eval records + M4 candidate
  evaluation (#796). Offenders: ["packages/maistro-design/src/maistro_design/stores.py:1
  score field 'design_quality_score'"]`.

The repository tree was not modified for this demonstration (the copy lives in `/tmp`).

### Pre-existing upstream condition (not this branch's)

`scripts/check-reachability.py` fails with one newly unreachable module,
`maestro.runs.admission_identity`. It reproduces **identically on `origin/develop`'s tip
alone** (exported with `git archive e20e9f52ea94` into a scratch tree → same single
offender), and this branch changes no `packages/*/src` file. Banking that module in
`quality/reachability-baseline.json` is develop's call, so the ledger was left
untouched here.
