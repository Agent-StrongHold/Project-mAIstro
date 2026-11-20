# Issue #2353 (Workspace cutover finish plan) — local validation evidence

Recorded 2026-11-16 by the CR2353 repair lane at head `4f22dac06a95`
(base `f8a2df966a1d` = current `origin/develop`; branch is exactly the two
docs commits, nothing else). Purpose: the hosted **Coverage gate (publish-set
floor + diff coverage)** failed on this PR's merge-queue evaluation, and the
failing leg's log named tests a docs-only change cannot influence. This note
is the local proof so the next worker does not re-derive it.

## Why the CI failure is not attributable to this branch

- The branch diff vs `f8a2df966a1d` is **two markdown files only**
  (`docs/architecture/WORKSPACE-CUTOVER-FINISH-PLAN.md`,
  `docs/superpowers/plans/2026-10-25-workspace-cutover-finish.md`). No Python,
  no workflow, no config.
- `scripts/check-diff-coverage.py` classifies non-`.py` changed files as
  `ignored` → the diff half of the gate has zero scope here.
- The publish-set floor measures Python coverage; docs cannot move it.
- The CI log's actual failures were in the **scripts producer** (root `tests/`
  suite, the last leg of the gate's combine step): a pytest-timeout
  (>30s) in `tests/test_devskim_scan_scope.py` plus
  `RuntimeError: Event loop is closed` lines — the classic overloaded-runner
  signature. Everything before that leg (including the 87% floor) had already
  passed in that run.

## Local rerun of the named gate (same commands as `.github/workflows/quality.yml`)

| Step | Command (abbreviated) | Result |
|---|---|---|
| publish-set producers | `coverage run --branch --source=…` over core/canvas/evolve/rsi/bootstrap suites, `--timeout=30` | 17,192+584+998+1,794+267 passed (2 container-image failures, see below) |
| floor | `coverage report --fail-under=87` | **93% ≥ 87% — pass** |
| scripts producer | `coverage run --append --branch --source=scripts -m pytest tests/ tests/test_model_check_consumer_claim.py packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30 -q` | 5,928 passed, 139 skipped (4 env errors, see below) |
| DevSkim test in isolation | `pytest tests/test_devskim_scan_scope.py --timeout=30 -q` | 21 passed in **9.8s** of the 30s budget |
| diff gate | `coverage xml` + `check-diff-coverage.py coverage.xml --base f8a2df966a1d…` | `0 changed file(s) measured` → pass |

## Environment-only failures seen locally (not branch defects, not CI defects)

1. `maistro-bootstrap/tests/test_container_sandbox.py::test_seed_leaves_ambient_credentials_on_the_host`
   and `maistro-rsi/tests/test_contained_fitness.py::test_real_evaluation_scores_every_signal_inside_one_container`
   both execute real docker containers against the **local**
   `maistro-builders:latest` image (built 2026-10-26 on this host). Failure
   modes were image-state artifacts (`exec: "git": executable file not found
   in $PATH` inside the container; the replay leg never launched). CI builds
   its own image state; the branch changes neither test nor image.
2. `tests/test_restore_oracle_characterization.py` (4 errors in the producer
   run): the throwaway `pgvector/pgvector:pg17` container never became ready
   because the host's pg17 image was stale. After `docker pull
   pgvector/pgvector:pg17`, all 6 tests in that file pass.

## Other gates run on the docs change

- `scripts/check-doc-links.py` → 3,192 files, 0 broken links (quality.yml runs it).
- `python3 scripts/check-retired-guidance.py` → ok, 479 governed files (ci.yml).
- `scripts/check-workspace-retirement.py` → OK, 89 ledger entries match the tree.
- `pytest tests/test_check_retired_guidance.py` → 32 passed.
- Fact anchors in the plan verified against the tree: `f52b8522be605…` (#2326)
  is an ancestor of `origin/develop` and of HEAD; ROADMAP lists #82 as v1.0
  blocker; `WORKSPACE-CUTOVER-PLAN.md` §9 defers #1051 to v1.1;
  `home_projections._goal_items` reads `goal_inspection`; Evolution has no
  route in `App.tsx`; the attention dismiss route and frontend client exist.

## Doc fix landed with this note

The plan's file pointers were corrected to the names that actually exist in
the tree (each verified): `workspace-conversation-continuity.spec.ts` (was
`workspace-chat-continuity.spec.ts`) and `components/AppShell.tsx` (was
`AppShell.tsx`). An execution plan whose paths 404 misdirects exactly the
agentic workers it addresses.
