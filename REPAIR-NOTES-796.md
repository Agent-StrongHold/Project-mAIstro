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

## Round 5 (2026-10-20, head `35f5e170a4`): the seven CI reds were ONE stale-tree defect

The merge-queue evaluation of `4231ab641f3a` reported seven red checks:

```
Quality / Reachability                     failure
Quality gate (Pillars 1–4, 7, 8)           failure
exact-debt-ledger                          failure
test                                       failure
Coverage gate (publish-set floor + diff)   failure
Supply chain (pip-audit)                   failure
security                                   failure
```

Read from the Actions job logs (read-only, `gh api .../actions/jobs/<id>/logs`), six of
the seven are the **same** failure and the seventh is a lockfile bump that develop had
already landed.

### The single root cause: `maistro.runs.admission_identity` was unreachable in a tree that was behind `develop`

`Quality / Reachability` (job `118771206805`):

```
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity  (maistro.runs.admission_identity)
##[error]Process completed with exit code 1.
```

`exact-debt-ledger` (job `118771207874`) failed inside `check-ratchet-provenance.py` on
the *same* ratchet, with the same arithmetic and the same candidate
(`caed309822ae` = PR #2208's synthetic merge):

```
ratchet: reachability  [python import graph …]
  baseline: base e20e9f52ea94
  candidate: caed309822ae
  168 unreachable modules  ->  169 unreachable of 1417 modules
```

`test` (job `118771207923`) failed on the two root-suite self-checks that assert the
committed reachability baseline against the tree:

```
FAILED tests/test_check_reachability.py::test_baseline_matches_the_tree
FAILED tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries
FAILED tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set
```

`Coverage gate (publish-set floor + diff coverage)` (job `118778406319`) failed with the
**same two test files** — that job's `combine` step re-runs the root suite, so it
inherited the `test` job's red rather than a coverage deficit. `Quality gate (Pillars
1–4, 7, 8)` (job `118773754408`) is the aggregator that requires every `quality-*`
leaf to succeed, so it went red because `quality-reachability` was red. That is four
checks, one defect.

**Mechanism.** `packages/maistro-core/src/maistro/runs/__init__.py` is the import edge
that makes `maistro.runs.admission_identity` reachable. At the tip this branch had
synced to (`e20e9f52ea94`) that file did **not** import it:

```
$ git show e20e9f52ea94:packages/maistro-core/src/maistro/runs/__init__.py | head -5
"""Canonical logical and physical execution lifecycle."""

from maistro.runs.concurrency import RunConcurrencyExceeded, RunConcurrencyLimits
```

`develop`'s next commit re-added the edge (`9417bb2f4ac`, the P1a/P1b codec merge
#2228/#1885):

```
$ git show 9417bb2f4ac:packages/maistro-core/src/maistro/runs/__init__.py | head -9
from maistro.runs.admission_identity import (
    AdmissionBinding,
    AdmissionRecordV2,
    CanonicalJsonObject,
    LegacyAdmissionRecord,
    RootAdmissionEnvelope,
)
```

So the module became reachable on `develop` while this branch — cut from the older
`develop` and never re-synced — still had the unreachable copy. Round 4 recorded this as
a "pre-existing upstream condition … develop's call"; that reading was wrong in the way
that matters: the condition was *this branch being behind*, and the fix is a sync, not
a ledger edit. Banking `maistro.runs.admission_identity` in
`quality/reachability-baseline.json` would have made the gate green by freezing a
module `develop` had just made reachable — a floor raise against the base, which the
ratchet forbids, and a false record of a wired module as dead code.

### The seventh red: `aiohttp` (supply chain)

`Supply chain (pip-audit)` (job `118771208433`) was an independent, dependency-only
failure:

```
::error::pip-audit found advisories outside the triaged allowlist:
  aiohttp==3.14.3 CVE-2026-111064 -> upgrade to 3.14.4
  aiohttp==3.14.3 GHSA-2g87-pp6c-29x5 -> upgrade to 3.14.4
  aiohttp==3.14.3 CVE-2026-111063 -> upgrade to 3.14.4
```

`security` is the workflow-level aggregate of the same `security` workflow, so it went
red for that leaf alone. This branch adds no dependency; the pinned `aiohttp` was
`3.14.3` in this branch's `uv.lock` and `3.14.5` in `develop`'s (the same commit that
re-added the import above bumped it). Both fixes therefore arrive with the sync.

### The repair: merge `origin/develop`

`35f5e170a4` — `Merge commit '9417bb2f4ac84447278639c9d8b747f6c8371970' into
auto-796`, conflict-free (`git merge-tree --write-tree HEAD origin/develop` → exit 0
before the merge). Nothing was hand-edited: the branch's whole delta against
`develop` is still the five issue surfaces, and the merge introduced **no**
production-code delta:

```
$ git diff --numstat origin/develop...HEAD
215	0	REPAIR-NOTES-796.md
 21	0	docs/architecture/CONVERGENCE-MATRIX.md
 91	0	docs/testing/inventory-notes/auto-796-develop-sync-2658c27c-resolution.md
 55	0	docs/testing/inventory-notes/m7-a7-eval-consumer-map.md
563	0	packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py

$ git diff --numstat origin/develop...HEAD -- 'packages/*/src'   # empty
$ git diff --numstat origin/develop...HEAD -- quality/           # empty
```

No ledger row was added, removed or re-banked: the reachability baseline and the vulture
per-identity ledger are byte-identical to `develop`'s, and the tree now matches them.

### Re-validation at `35f5e170a4` (all green)

| Command (CI's exact arguments) | Outcome |
| --- | --- |
| `uv run python scripts/check-reachability.py` | exit 0 — `1417 production modules, 168 unreachable` (the 169th is reachable again) |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | exit 0 — `168 unreachable module(s) -> 168`, every ratchet `no candidate-approved expansion` |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 — `1326 reviewed identities -> 1326 findings` |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-shipped-surface-truth.py` | exit 0 |
| `uv run pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_reachability_scanner.py tests/test_reachability_source_universe.py -q` | 54 passed |
| `uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=120` | 5395 passed, 139 skipped, 0 failed (323.9s) |
| `uv run pytest packages/maistro-core/tests/fitness -v --timeout=30` | 34 passed (CI's `Quality / Architecture fitness` command) |
| `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -q` | 7 passed (the M7-A7 contract file) |
| `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -q` | 13 passed (M5 invariant) |
| `uv run pytest packages/maistro-design/tests -q` | 575 passed, 1 skipped |
| `uv run python scripts/check-suite-inventory.py` | exit 0 — 21 suites match, 32394 unique identities |
| `uv run python scripts/check-convergence-matrix.py` | exit 0 — 52 subsystems / 1417 modules, 168 unreachable attributed |
| `uv run python scripts/check-doc-links.py` | exit 0 — every relative markdown link resolves |
| `uv run python scripts/check-contract-markers.py` | exit 0 |
| `uv run python scripts/check-merge-markers.py` | exit 0 |
| `uv run python scripts/check-backlog-consistency.py` | exit 0 — 167 backlog items parse |
| `uv run python scripts/check-test-duplicates.py` | exit 0 |
| `uv run python scripts/check-reachability-dispositions.py` / `-provenance.py` / `check-promotion-surface.py` / `check-promotion-surface-provenance.py` / `check-security-inventory.py` / `check-model-egress.py` / `check-cross-package-imports.py` / `check-owned-store-access.py` / `check-agent-store-writes.py` / `check-wiring-reads.py` / `check-radon-baseline.py` | all exit 0 |
| `uv run ruff check .` | exit 0 — `All checks passed!` |
| `uv run ruff format --check .` | exit 0 — `3363 files already formatted` |
| `uv run mypy <7 src trees>` | exit 0 — `Success: no issues found in 906 source files` |
| `uv pip freeze --exclude-editable > deps.txt && uvx pip-audit --strict --format=json -r deps.txt` + `uv run python scripts/pip_audit_gate.py pip-audit.json` | exit 0 — `pip-audit OK (1 known, all triaged in ALLOWED)`; the `aiohttp` advisories are gone with `aiohttp==3.14.5` |

### One local-only red, and why it is not a defect

The root suite first reported
`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
→ `unclassified quality state: quality/ac-state.json`. That file is **generated and
git-ignored** (`.gitignore:81`; "Generated by `scripts/check-ac-state.py` on every
run"). Running `scripts/check-ratchet-provenance.py` in the worktree creates it, and a
root-suite run that follows sees an unclassified `quality/*.json` that a CI checkout
never has. The file was moved aside (preserved at `/tmp/ac-state.json.generated-local`,
not deleted) and the test passes:

```
$ uv run pytest tests/test_branch_independence_repository.py -q
1 passed
```

CI's `test` job starts from a clean checkout of the synthetic merge, so this artifact
cannot exist there — consistent with the job's own log, whose only failures were the
three reachability assertions above. With the artifact absent, the whole root suite is
green at the merged head:

```
$ uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=120
5395 passed, 139 skipped, 19 warnings in 323.88s (0:05:23)
```

### The full gate battery at `35f5e170a4`

Every `scripts/check-*.py` that takes no CI-only arguments was swept with
`RATCHET_BASE_REV=origin/develop`; all exit 0 (`check-ac-state`, `check-adr-index`,
`check-adr-status-language(-provenance)`, `check-agent-store-writes`,
`check-api-route-contracts`, `check-backlog-consistency`, `check-build-context`,
`check-citation-status(-provenance)`, `check-closure-targets`, `check-compose-resources`,
`check-compose-secrets`, `check-connection-credentials`, `check-contract-markers(-provenance)`,
`check-convergence-matrix`, `check-credential-authority`, `check-cross-package-imports`,
`check-dependency-namespaces`, `check-deployment-claims`, `check-doc-links`,
`check-durable-table-inventory`, `check-enumerations-provenance`, `check-execution-lifecycles`,
`check-extension-imports`, `check-extension-scaffold`, `check-foreign-harness-egress`,
`check-frontend-api-routes`, `check-frontend-typed-client`, `check-image-inventory`,
`check-image-pins`, `check-install-functions`, `check-lifecycle-provenance`,
`check-merge-markers`, `check-model-egress`, `check-owned-store-access`,
`check-principal-identity`, `check-promotion-surface(-provenance)`, `check-public-routes`,
`check-radon-baseline`, `check-ratchet-provenance`, `check-reachability`,
`check-reachability-dispositions(-provenance)`, `check-reachability-provenance`,
`check-reference-extension`, `check-release-consistency`, `check-retired-guidance`,
`check-route-permissions`, `check-secret-field-labels`, `check-security-inventory`,
`check-shell-execution(-provenance)`, `check-shipped-surface-truth`,
`check-suite-inventory`, `check-test-duplicates`, `check-uv-setup`, `check-wiring-reads`,
`check-workflow-inventory`, `check-workflow-write-safety`, `check-workspace-retirement`).
The three that need arguments were run with them —
`check-formal-oracle-independence.py --base origin/develop` (exit 0),
`check-m1-convergence-freeze.py --base origin/develop` (exit 0) — and
`check-vulture-baseline.py` only with **CI's** arguments
(`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`), because its
defaults (`packages`, `tests`) bank rows the blocking job can never see and fail by
design (see `AGENTS.md`).

### Residuals

- Acceptance criterion "PR is `feat/m7-a7-eval-consumer-map` off `develop`" is
  dispatcher-owned GitHub state. Lane workers may not push or open PRs, so the branch
  name (`auto-796`) and the PR's existence are unverifiable locally by construction.
- The `Coverage gate`'s publish-set floor (87%) and diff-coverage thresholds are not
  re-measured locally: they need the CI coverage producers' artefacts. The diff-coverage
  half is vacuous for this branch by construction — the branch changes **no** file under
  any `MEASURED_ROOTS` tree (`git diff --numstat origin/develop...HEAD -- 'packages/*/src'`
  is empty) — and the job's own log shows it failing in the root-suite re-run, not in
  the coverage arithmetic.
- `pip-audit` was run locally against the installed environment (`--extra dev`), which
  is a subset of CI's `--all-extras` install; the advisories that decided the CI red
  (`aiohttp`) are covered by it, but a CVE in an extra-only dependency would not be
  visible locally.

## Round 6 (2026-10-20, head `e0556fafd`): post-queue re-verification — no repair needed

The merge-queue evaluation that opened this round reported every required check
**green**; the only block was GitHub merge-queue contention (`GH006`, "branch queued in
GitHub merge queue"), which no lane action resolves. The develop sync that cleared the
seven earlier reds is already in this head: `e0556fafd` is `Merge commit
'c2d7209f1dbc…' into auto-796`, `origin/develop` is still `c2d7209f1dbc`, and
`git merge-base --is-ancestor origin/develop HEAD` → true. The branch is fully synced,
so there was no conflict to resolve; the merge delta is the five issue surfaces only and
`git diff --numstat origin/develop...HEAD -- 'packages/*/src' quality/` is empty.

Re-validation at `e0556fafd` with CI's exact arguments (all exit 0):

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -v` | 7/7 pass |
| `uv run pytest packages/maistro-core/tests/fitness -q` | 34 pass |
| `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -q` | 13 pass (M5 invariant) |
| `uv run pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_reachability_scanner.py tests/test_reachability_source_universe.py -q` | 54 pass |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | exit 0 — 168 → 168 unreachable, no candidate-approved expansion |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 — 1326 reviewed identities → 1326 findings |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-shipped-surface-truth.py` | exit 0 |
| `uv run python scripts/check-reachability.py` | exit 0 — 1420 production modules, 168 unreachable |
| `uv run python scripts/check-suite-inventory.py` | exit 0 — 21 suites match |
| `uv run python scripts/check-convergence-matrix.py` | exit 0 — 52 subsystems / 1420 modules |
| `uv run python scripts/check-doc-links.py` | exit 0 — 0 broken links |
| `uv run python scripts/check-contract-markers.py` / `check-merge-markers.py` | exit 0 |
| `uv run ruff check .` / `uv run ruff format --check <file>` | clean / already formatted |

Exact-debt-ledger's three leaves (`check-ratchet-provenance.py`,
`check-shipped-surface-truth.py`, `check-vulture-baseline.py` with the workflow's
`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) all pass, so the
per-identity vulture ledger needed no amendment — there were no unbanked identities and
no eliminated identities to remove. The previously-red supply-chain leaf is resolved by
the sync (`uv.lock` pins `aiohttp==3.14.5`).

**Bank audit.** A re-scan of `packages/maistro-design/src` with the contract's own
def-name regex returns exactly the six `_DESIGN_SURFACE_BANK` identities — no unbanked
match and no bank row hiding a genuine second loop. `consistency.py` is read-only,
deterministic and proposal-only (module docstring: "no write path to any store" …
"not a self-improvement authority"), and `_evaluate_upgrade` is a preflight returning
`can_upgrade=not blocked` — neither scores a design Goal nor promotes anything.

**Tripwire liveness re-proved out-of-tree** (repo untouched): a copy of the contract
file under `/tmp/m7a7-verify/repo/…` with `maistro_design/engine.py` importing
`maistro_evolve.cycle` + `maistro_rsi.local_loop` and `stores.py` holding
`design_quality_score = 0.9` made the two named test functions **fail**, naming the
offenders (`engine.py:1 import maistro_evolve.cycle`, `engine.py:2 from
maistro_rsi.local_loop`). The tree was not modified for the demonstration.

**Local-only artifact (not a defect).** `quality/ac-state.json` is generated and
git-ignored (`.gitignore:81`, written by `scripts/check-ac-state.py`); running the
ratchet gate creates it, after which `tests/test_branch_independence_repository.py`
reports it as an unclassified quality state surface. CI checks out clean, so it cannot
exist there. The file was left in place (ignored, untracked).

**Residuals.** The PR branch name (`feat/m7-a7-eval-consumer-map` in the issue text vs
the campaign's `auto-796`) and the push are dispatcher-owned and unverifiable locally.
The coverage publish-set floor and full `--all-extras` `pip-audit` were not re-run
locally; the diff-coverage half is vacuous for this branch (no `packages/*/src` delta)
and the `aiohttp` advisory is verified fixed by the lockfile.

## Round 7 (2026-10-20, head `4ee8f4120`): post-queue re-verification, liveness proven **in-tree**

No repair was required again. The dispatch reported the previous merge-queue evaluation
**green**, with the block being GitHub merge-queue contention (`GH006`) — dispatcher-owned
state, not a code defect — and the vulture/exact-debt-ledger repair clause was conditional
("fix what is genuinely dead"). Both were re-checked rather than assumed.

### The branch is still exactly synced (nothing to merge)

```
$ git fetch origin develop && git rev-parse origin/develop
c2d7209f1dbc1039e8ca9d99444b88ded3bbe26b
$ git merge-base --is-ancestor origin/develop HEAD && echo synced   # synced
$ git rev-list --count HEAD..origin/develop
0
```

`origin/develop` has not moved since round 6, so there is **no develop sync conflict** —
neither a rebase nor a merge base exists to resolve. The branch delta against
`origin/develop` is still the five issue surfaces (`git diff --stat` → 6 files, 1299
insertions, 0 deletions once the two sync notes are counted), and
`git diff --numstat origin/develop...HEAD -- 'packages/*/src' quality/` is empty: this
branch changes no production code and no per-identity ledger row.

### Gates re-run at `4ee8f4120` (all exit 0)

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -x -q` | 7 passed |
| `uv run pytest packages/maistro-core/tests/fitness -q` | 34 passed |
| `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -x -q` | 13 passed (M5 invariant) |
| `uv run pytest packages/maistro-design/tests -x -q` | 575 passed, 1 skipped |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3370 files already formatted |
| `uv run mypy <7 src trees>` | no issues in 908 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 — 1326 reviewed identities → 1326 findings |
| `uv run python scripts/check-reachability.py` | exit 0 — 1420 production modules, 168 unreachable |
| `uv run python scripts/check-ratchet-provenance.py` | exit 0 — 0 lifecycle violations |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-shipped-surface-truth.py` | exit 0 |
| `uv run python scripts/check-suite-inventory.py` | ok — 21 suites (`maistro-core/tests` 16826 = baseline + `+7`) |
| `uv run python scripts/check-convergence-matrix.py` | OK — 52 subsystems / 1420 modules |
| `uv run python scripts/check-doc-links.py` | 2485 files, 0 broken links |
| `uv run python scripts/check-contract-markers.py` | OK (the 2 `undefined-marker-kind` rows are pre-existing, neither is this file) |
| `uv run python scripts/check-test-duplicates.py` | ok — 1639 files, 0 byte-identical |
| `uv run python scripts/check-merge-markers.py` / `check-retired-guidance.py` | ok / ok |

The vulture ledger needed **no amendment**: with CI's exact arguments there are no
unbanked identities and no banked identity that this branch's fix eliminated
(`packages/*/src` is untouched by the branch).

### Liveness proven **in the real tree**, not only out-of-tree

Rounds 4 and 6 demonstrated liveness on a `/tmp` copy, where `_REPO_ROOT` resolved to a
*synthetic* tree — that proves the scanner helpers catch their shapes, but not that the
contract's real inventories (`_DESIGN_SRC`, the Hive `routes/design*.py` /
`services/design*.py` globs, `_EVOLVE_SRC`, `_RSI_SRC`) are what they scan. This round
planted each forbidden shape in the **actual repository paths**, ran the named test
function, and removed the probe in a `trap … EXIT` so the tree was restored in the same
script:

| Probe (real path) | Test function | Result |
| --- | --- | --- |
| `maistro_design/_probe796loop.py` → `import maistro_evolve.cycle` | `test_design_loop_does_not_import_rsi_or_evolve` | **failed** at `test_m7_a7_eval_consumer_map.py:331` |
| `hive-conductor/backend/routes/design_probe796.py` → `from maistro_rsi.gateway import …` | `test_design_loop_does_not_import_rsi_or_evolve` | **failed** at `:331` (the `design*.py` glob is live) |
| `maistro_design/_probe796scorer.py` → `class DesignCritic` | `test_maistro_design_declares_no_scoring_or_promotion_surface` | **failed** at `:389` |
| `maistro_design/_probe796store.py` → `design_quality_score = 0.9` | `test_no_design_quality_scores_stored_outside_the_canonical_homes` | **failed** at `:429` |
| `maistro_evolve/_probe796fitness.py` → `from maistro_design.types import …` | `test_evolve_and_rsi_do_not_reach_the_design_rubric_domain` | **failed** at `:357` |

Five probes, five failures, each on the intended assertion — so the green run on
`develop` is a proven scan of the real inventories, not a vacuous one. `git status
--porcelain` was empty immediately afterwards: the probes were the only tree change and
they are gone.

### Bank audit re-confirmed

Re-scanning `packages/maistro-design/src` with the contract's own def-name regex yields
**exactly** the six `_DESIGN_SURFACE_BANK` identities — nothing unbanked is hiding behind
the bank and no bank row is stale. Independent of the bank: `grep -rn score
packages/maistro-design/src packages/hive-conductor/backend/(routes|services)/design*.py`
returns nothing, so no design-quality score is stored anywhere in the design loop today;
the tripwire is preventive against the shape reappearing.

### `quality/ac-state.json` — artifact removed

Round 6 left the generated, git-ignored `quality/ac-state.json` in place, which made
`scripts/check-branch-independence.py` fail locally on an "unclassified quality state"
that cannot exist in a CI checkout. Running `check-ac-state.py` regenerated it this round;
it was backed up to `/tmp/ac-state-796-backup.json` and removed, after which
`check-branch-independence.py` → `PASS: every quality JSON state surface has one
branch-independence representation`. Only an ignored file was touched; `git status` is
clean.

### Residuals (unchanged from round 6)

The issue's acceptance line "PR is `feat/m7-a7-eval-consumer-map` off `develop`" is
dispatcher-owned GitHub state (this campaign's branch is `auto-796`); lane workers may
not push or open PRs, so it is unverifiable locally by construction — the branch *is* off
`develop`, with `origin/develop` a direct merge-base ancestor. The coverage publish-set
floor and a full `--all-extras` `pip-audit` were not re-run; the diff-coverage half is
vacuous here (no `packages/*/src` delta) and round 5 verified the `aiohttp==3.14.5`
lockfile fix.
