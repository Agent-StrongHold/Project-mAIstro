# REPAIR-NOTES — #49 round (branch `auto-49`)

Job `47222171c9804e449639153a60bbef1f`, 2026-10-25. Incoming head
`1fab9f4c4`; develop base for this round `09d56b6a0`. Two blocks carried in:
the preserved develop-sync conflict, and the red `test` job from the last
merge-queue evaluation (run 40184962631, job 121143712142).

## 1. Develop sync (the preserved conflict block)

The worktree arrived mid-merge with `MERGE_HEAD = 4f8811f92` (develop's
DevSkim triage #2111, carrying #2258/#2270/#2312/#2314/#2318) and one
conflict: `docs/architecture/CONVERGENCE-MATRIX.md`. Resolution, committed as
`62876ba03`:

- **Planning and wave orchestration row** — took develop's side: `none`
  unreachable with the `#2314` SPEC-255 annotation. The merged
  `quality/reachability-baseline.json` has no unreachable
  `maistro.orchestrator.*`/waves modules, so the claim is consistent with the
  ratchet the checker enforces.
- **Builders pipeline row** — kept this branch's side: the #459 scenario-1
  Builders → canonical Run → Conductor execution evidence
  (`tests/cross_product_parity`, cancelled mid-flight through the same id).
  This lane implements #49; the row's claim is proven by the suite itself.

`origin/develop` had advanced five more commits past `4f8811f92` (up to
`09d56b6a0`, EPIC M5-B); merged cleanly as `05fd45ec8` with no remaining
conflicts. `git diff --numstat origin/develop -- quality/` is empty — no
silent ledger row loss; the frontend-typed-client/image-pins/dispositions
deltas seen mid-merge were develop's own later commits arriving.

## 2. The red `test` job — actual root cause

The job log shows `RuntimeError('Event loop is closed')` blocks rendered as
`##[error]`, but those lines sit inside pytest **warnings summary** sections
(aiosqlite `_connection_worker_thread` raising after its loop closed —
`PytestUnhandledThreadExceptionWarning`). Every pytest step passed:

- maistro-server 645, turing 225, turing/backend 125, design 662,
  ext-harness 273, ext-sdk 147, root `tests/` 5653, hive backend 4034,
  cross-suite 10442 — all green at the pre-sync head.

The only real failure is the step after them:
`python scripts/check-suite-inventory.py` →
`DRIFT tests/: expected 5888, collected 5889` (net +1), exit 1. A suite
gained a node ID without a matching ledger entry — the branch's own earlier
state lagged develop's ledger, which #2334/#2336 and EPIC M5-B moved together
with the tests they added.

**Fix: the develop sync itself.** After merging develop through `09d56b6a0`
the ledger and the trees reconcile (every unfolded `inventory-delta` note on
this branch also exists on `origin/develop`; the branch's only test diff,
`tests/cross_product_parity/`, is node-count neutral):

```
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run python scripts/check-suite-inventory.py
→ ok: 21 suite(s) match the recorded inventory
```

## 3. Validation at the merged head (`05fd45ec8`)

- `scripts/check-convergence-matrix.py` — OK, 52 subsystems / 1469 modules.
- `scripts/check-suite-inventory.py` (full, 21 suites) — ok.
- `uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=60` —
  5800 passed, 139 skipped. One local-only failure
  (`test_every_quality_json_state_surface_is_classified_once` on
  `quality/ac-state.json`) is a **gitignored generated artifact** of
  `scripts/check-ac-state.py` (`.gitignore:86`) left by an earlier local run;
  moved to the job's `salvage/`, after which the test passes. CI checkouts
  never contain the file.
- `uv run pytest packages/maistro-core/tests/builders -q` — 201 passed,
  1 xfailed.
- `uv run pytest tests/cross_product_parity -q` — 26 passed (includes the
  real #459 scenario-1 Builders→Conductor execution).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1263 reviewed identities == 1263 findings,
  exit 0 (CI's exact arguments; no ledger amendment needed).
- `uv run ruff check .` / `ruff format --check .` — clean.
- `uv run mypy packages/maistro-core/src` — no issues in 830 files.

No test was added or removed in this round, so no new inventory note is
required; `docs/testing/inventory-notes/49-builders-canonical-cutover.md`
already records the lane's count-neutral parity-suite change.

## 4. Verification round at `cc2b7913b` (merge of develop `4019249e`)

Re-validation after the sync merge, against the `test` job's own steps
(ci.yml), because the last merge-queue evaluation (run 40184962631) red at
`bc9bd8b` predates it and `bc9bd8b` is an ancestor of this head:

- `uv sync --locked --extra dev --extra bootstrap` (CI's exact extras; the
  `--extra bootstrap` member is not installed by `--extra dev` alone and two
  `test`-job suites need it).
- `scripts/check-suite-inventory.py` — **ok: 21 suite(s) match** (tests/
collects 6032 == baseline; the bc9bd8b `DRIFT tests/: expected 5888,
collected 5889` is gone with the synced ledger). Interpreting one local
artifact: the two `bare_python=True` hive suites fail collection when the
check is driven by an interpreter without the hive backend requirements —
ci.yml installs those system-wide (`uv pip install --system -r ...requirements.txt`)
before this step; driving the check via `uv run python` (populated
interpreter, same recipes) is the faithful local reproduction.
- Cross-suite leakage step, CI's exact argv and env — `REQUIRE_AUTH=false
MAISTRO_DRY_RUN=1 uv run pytest tests/ packages/hive-conductor/backend/tests
packages/maistro-design/tests -q --timeout=60` — **10617 passed, 169
skipped** (this step's trees produced the `Event loop is closed` aiosqlite
thread warnings in the red log; they are warnings, `filterwarnings=error` is
not set, and the step is green).
- Remaining per-tree pytest steps — server+turing+turing backend+ext-harness
+ext-sdk: **1416 passed, 10 skipped**.
- `tests/cross_product_parity` development mode (the `cross-product-parity`
job): **26 passed**. Strict mode (`MAISTRO_PARITY_STRICT=1`, a
workflow_dispatch-only workflow): the two Builders strict tests pass here
and failed on the develop base `4019249e` (verified in a throwaway worktree
at that sha: 8 strict failures there, 6 here — the remaining 6 are
scheduler/evolve/golden scenarios owned by #231/#51/#463, pre-existing and
documented in the inventory note); no regression, net -2.
- `scripts/check-test-duplicates.py` — ok. `scripts/check-convergence-matrix.py`
— OK, 52 subsystems / 1475 modules. `uv run mypy packages/maistro-core/src`
— no issues in 830 files. `npm audit --audit-level=high` (canvas frontend,
lockfile-based like CI) — found 0 vulnerabilities.
- Acceptance spot-checks at this head: `CanonicalGraphPipelineExecutor` is
constructed in production modules (`builders/interactive.py:203`,
`builders/dag.py:590`, `builders/pipeline.py:634`); legacy
`GraphPipelineExecutor` has no class definition left in src (only a
historical comment at `builders/graph_executor.py:209`); `StageStatus` is
projection-only (canonical records -> receipts, `graph_executor.py:742`);
the CLI TUI executes through `BuildersExecutionSpine.executor()` with
`TurnRunner` demoted to the model-driving loop (`cli/_builders_tui.py:194-227`).

Unverified locally (infrastructure-bound, tree content identical to green
develop `4019249e`): the two frontend `npm ci`+lint+build steps and the
OpenAPI types diff (both frontends and the hive backend are untouched by
this branch, so the steps' inputs are byte-identical to develop's green run).

## 5. Independent verification round at `c6d05e5cc` (job `de9521269e`)

Re-verified every #49 acceptance criterion from scratch at this head; no code
changes (tree was already clean, head unchanged). Executed evidence:

- `uv sync --locked --extra dev --extra bootstrap` — ok (bootstrap extra
  restored after the driver's dev-only sync uninstalled it).
- `pytest packages/maistro-core/tests/builders -q` — **203 passed, 1 xfailed**.
- `pytest tests/cross_product_parity -q` (dev mode) — **26 passed**.
- `MAISTRO_PARITY_STRICT=1 pytest tests/cross_product_parity -v` — **20
  passed, 6 failed**; the two Builders strict tests
  (`test_builders_created_work_has_public_conductor_inspection_seams`,
  `test_builders_required_scenario_emits_strict_closeout_evidence`) PASS; the 6
  failures are `DependencyUnavailable`/`ScenarioAbstained` guards naming open
  #231 (schedule x2), #51 (evolve x2), #463 (golden x2) — outside this lane.
- Code census re-checked by grep: no `class GraphPipelineExecutor` anywhere in
  `packages/*/src`; `CanonicalGraphPipelineExecutor(` constructed at
  `builders/interactive.py:203`, `builders/dag.py:590`, `builders/pipeline.py:634`;
  `cli/_builders_tui.py:233-235` executes via `BuildersExecutionSpine.open()` ->
  `spine.executor().execute(...)` with `TurnRunner` only as the node's model
  strategy; `StageStatus` is a projection derived from canonical records
  (`graph_executor.py:742-744`); builders `RunStatus` is canonical
  `maistro.runs.model.RunStatus`; `_load_spec_context` retains domain spec state
  (`pipeline.py:548`). Attempt chronology pinned by
  `test_gate_revision_is_new_node_run_and_attempt_evidence_with_feedback`
  (4 NodeRuns / 4 distinct Attempts for one gate revision) and
  `test_revision_dominates_a_concurrent_wave_after_it_settles` (documents #1067
  defect 1). #1067 (closed 2026-09-23) and #1068 (closed 2026-10-25) confirmed
  closed in the captured dispatch snapshot.
- `scripts/check-suite-inventory.py` (CI env `REQUIRE_AUTH=false
  MAISTRO_DRY_RUN=1`) — **ok: 21 suite(s) match** (the bc9bd8b
  `DRIFT tests/: expected 5888, collected 5889` root cause is gone with the
  develop sync).
- `scripts/check-convergence-matrix.py` — OK, 52 subsystems / 1475 modules;
  Builders row is MIGRATE with the legacy executor parity-only (census updated).
- `scripts/check-reachability.py` — rc=0, 104 unreachable, **zero builders
  modules** in `quality/reachability-baseline.json` (identical to the develop
  base: reclassification is truthful, no fake roots).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1256 reviewed identities == 1256 findings, rc=0
  (CI's exact arguments; no ledger amendment needed).
- `uv run mypy packages/maistro-core/src` — no issues in 830 files.
- `uv run ruff check .` / `ruff format --check .` — clean (matches the driver's
  check-1/check-2 logs).
- pyproject.toml has **no `filterwarnings = error`** (grep rc=1), so the red
  run's `RuntimeError('Event loop is closed')` aiosqlite thread lines are
  warnings-summary noise and cannot fail a pytest step; the only real failure at
  `bc9bd8b` was the suite-inventory drift step, resolved by the sync.
