# Repair round — #891 (M8-A11 Z3/SMT research leaf), head `a06e834e`

Round: L891 repair, job `d0d02cf93fad4b40b2cc098f35b6917c`, starting head
`a06e834e4b2566a134d29917ef6209d172b5c486` (exact match), develop base
`bb9a7fbbc7524be0f63d3b74b76a0edda459b60a`, merge-base with `origin/develop`
`c29e0ea7094198095c107e3583dbfd5e50009a5d`.

## Driver checks (job `check-*.log`, all returncode 0)

| Check | Result |
|---|---|
| `uv sync --locked --extra dev` | 260 packages resolved |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3439 files already formatted |
| `uv run pytest packages/maistro-core/tests/scheduling/_z3_fire_contract.py packages/maistro-core/tests/scheduling/test_engine_z3_conformance.py -q -x` | 13 passed |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | ok: matches recorded inventory (17414 collected) |

## Independent re-validation run this round

- `pytest packages/maistro-core/tests/scheduling/_z3_fire_contract.py
  packages/maistro-core/tests/scheduling/test_engine_z3_conformance.py -v` —
  **13 passed in 2.41 s** (whole-grid conformance + uniqueness, teeth guards,
  unsat-core explainability, identity-aware starvation queries, never-ending
  run witness, short-circuit/horizon pins, solver-boundary scans).
- `pytest packages/maistro-core/tests/scheduling/ -q` — **287 passed,
  37 skipped** (experiment does not disturb the sibling suite).
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` — ok,
  re-run live.
- `scripts/check-doc-links.py` — 2620 files, 0 broken relative links.
- `ruff check .` / `ruff format --check .` — clean, re-run live.
- Production boundary, independently of the test: `grep -rn "import z3|from
  z3" packages/*/src` → empty; `grep -rn z3 packages/*/pyproject.toml
  extensions/*/pyproject.toml` → empty; `z3-solver` declared only in the root
  `pyproject.toml` dev lists (`uv.lock` rows: root workspace dev extra +
  transitive via `crosshair-tool`, itself root-dev-only). The issue's non-goal
  (no solver runtime dependency in production) holds.

## CI `test` gate failure at this head — classified transient, not a tree defect

The only failing check at `a06e834e` is the `test` job
(run 39710900826/job 119601725406). Its log ends in
`npm audit --audit-level=high` → `npm error audit endpoint returned an error`
→ exit 1: an npm registry audit-endpoint failure, not a test result. Evidence
it is not this branch:

- The step runs in `packages/maistro-canvas/frontend`
  (`.github/workflows/ci.yml:690`); the branch delta vs the merge-base
  (11 files) and the develop-side delta (2 commits) touch **no**
  `package.json`, `package-lock.json`, or frontend file; `git diff HEAD
  origin/develop -- .github/workflows/ci.yml` is empty.
- Re-running the exact command locally against the same lockfile now exits **0**
  (2 moderate findings, below the `--audit-level=high` threshold): the
  endpoint answers, the lockfile has no high-severity finding.
- All other 70+ required checks at this head are green, including every
  Python test leg (postgres pg17/pg18, MinIO, hive-conductor e2e), quality,
  SAST, coverage, and exact-debt-ledger.

No develop sync conflict: `git merge-tree $(git merge-base HEAD
origin/develop) HEAD origin/develop` contains no conflict markers (the only
`<<<<<<<` hit is quoted prose inside a develop-side repair note). The PR's
`behind` state is GitHub-neutral; per lane rules no merge is required for
this failure class and none was performed.

## Repair applied (focused)

The repo's documented M8 convention (`docs/research/README.md`: "This folder
is the in-repo home of M8 research notes"; M8-A leaves that produce research
notes keep them there and are indexed) was unmet by #891: the experiment
record lived only at `docs/testing/z3-smt-decisions-evidence.md` with no
`docs/research/891-*` note and no index row, unlike every sibling leaf
(#882, #884, #885, #887, #888, #889, #890, #894, #896, #897, #918). Repaired:

- **Added** `docs/research/891-z3-smt-fire-decision.md` — the M8-A research
  note in sibling format (hypothesis, canonical target, baseline, method,
  findings, measurements, failure class, WATCH disposition + re-engagement
  trigger), cross-linking the full evidence record. Content is transcribed
  from the committed evidence; no new claims.
- **Updated** `docs/research/README.md` — index row for #891 (M8-A11, WATCH)
  and #891 added to the leaves-with-notes list.

No test counts changed; no inventory delta required beyond the existing
`docs/testing/inventory-notes/891-z3-smt-fire-decision.md` (+13, already
banked and matching the recorded inventory).

## Acceptance vs issue #891

| Issue criterion | Evidence |
|---|---|
| One representative constraint-heavy decision encoded directly in Z3 | `packages/maistro-core/tests/scheduling/_z3_fire_contract.py` (568 lines, real `z3` encodings) over `maistro.scheduling.engine.evaluate` |
| Satisfiability + counterexample questions | `conforms`/`unique_beyond`/`divergent_witness`/`impossible_fire_core` (unsat cores), `BufferedStarvationModel` properties; 13 node IDs green |
| Comparison against current procedural logic/tests | Whole-grid differential (336 cells) against `evaluate`; baseline (`test_engine.py`, 21 tests) recorded in the evidence doc |
| Measurements: effort, performance, explainability, maintenance, clarify-vs-duplicate | `docs/testing/z3-smt-decisions-evidence.md` measurements table + findings (functional-spec reduction, 3 false positives, costs) |
| GRADUATE / INCUBATE / REJECT / WATCH disposition | WATCH with concrete re-engagement trigger (evidence doc + `docs/research/891-z3-smt-fire-decision.md` + README index) |
| No solver runtime dependency in production | `z3-solver` dev-only; source+manifest scan test green; independent greps clean |
| Defect routing to M0–M7 owners | None found; explicitly recorded |
