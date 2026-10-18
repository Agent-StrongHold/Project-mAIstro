# Issue #65 repair validation

## Frozen scope

- Assigned issue: #65 only; worktree `/home/dev/Git/wt/auto-65`, branch `auto-65`.
- Starting head verified: `e9f093cb7151eb99eb072af6062620e8627c8e5a`; base: `35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`.
- Starting worktree clean. No incoming work to salvage.
- Evidence snapshot: supplied `dispatch-context.json`, issue body's 13 acceptance criteria, five prior findings, and explicit vulture CI-repair instruction. No GitHub mutations or refreshed discovery.
- File scope: existing #65 core Goal context and Conductor inspection implementation/tests/UI, related ADRs and workflow gates, this validation note; `quality/vulture-baseline.json` only if actual scan establishes reviewed retained identities. New tests require an inventory note.
- No `check-*.log` files were present in the supplied job directory on initial inspection.
- Assumption: this is a writer repair, not a read-only verifier run. Earlier readiness claims are not evidence.

## Progress

1. Verified starting HEAD, clean state, issue criteria and changed-file scope.
2. Requested exact vulture command passed: 1,322 findings / 1,322 reviewed identities, zero unclassified. No evidence supports a ledger amendment; none planned. Missing guessed ADR/service filenames were not found and skipped; resolved actual ADR and store paths from the local snapshot instead.
3. Read accepted ADR-081226-9944 (ownership/physical execution), ADR-092326-7ed7 (Workspace Agent), ADR-091726-7c2a (confirmed interview before Goal commit). Reconciliation: #65 cannot repair absent Goal admission by minting Goals for arbitrary chat/DAG Runs; that would violate the interview gate. Existing creative Graph producer stamps `goal_id`/`goal_revision` in Run provenance (`creative_graph.py:394`), not immutable Run admission fields, so a claim that all production Goal context is unreachable would be too broad. The inspected Conductor producers still do not bind Goals.
4. Confirmed remaining structural gaps: Goal list/detail discover only retained Conductor Run projections; scoped Goal reader has no discovery API. Goal disposition is Run-status-derived, not a reconciliation decision. Canonical-only Run detail exposes no canonical Events, effects or approvals. 
5. Focused baseline passed: 37 Conductor inspection tests. Found and reproduced two exact-revision integrity defects via new tests (both failed with stale values before the repair): old legacy revision facts were borrowed for a sparse newer revision; canonical empty condition lists revived stale provenance via scalar fallback. Fixed only those projection fallbacks, preserving historical provenance and canonical ownership. Post-fix: 39 Conductor inspection tests and 6 core Goal context tests passed; root Ruff check and format check passed (3,330 files). Inventory note records +2 Conductor tests. 
6. Full changed-package validation passed: `uv run pytest packages/hive-conductor/backend/tests -x -q` -> 3,753 passed, 19 skipped, 33 warnings, 195.34s. Warnings include existing audit serializer shape and SQLite worker/event-loop cleanup warnings; no test failures.
7. Gates passed: suite inventory for Conductor (3,772) and core (16,469), route permissions (41 prefixes, zero undeclared), frontend API routes (185 sites), API route contracts (296 handlers), and repeat exact vulture scan (1,322/1,322). `git diff --check` passed.
8. Existing browser roundtrip tests were inspected, not executed: they stub both Goal and Run doors and cannot prove producer reachability or persistent restart. No browser readiness claim is made. The initially guessed frontend-relative spec/config paths were not found and skipped; actual spec is `packages/hive-conductor/tests/e2e/goal-run-roundtrip.spec.ts`.
9. Both frontend TypeScript projects passed `./node_modules/.bin/tsc -p tsconfig.json --noEmit` and `./node_modules/.bin/tsc -p tsconfig.node.json --noEmit` from the frontend directory. Read the complete interoperability ontology: non-Goal infrastructure Runs remain valid; exact Goal revision cannot be rewritten by later evidence. The focused fix enforces that existing contract without introducing authority.

## Acceptance audit (issue body order)

Passing projection tests do not prove a reachable end-to-end product workflow.

| # | Criterion | Executed evidence / remaining gap |
|---|---|---|
| 1 | Consume #1036, not a new Run authority | Existing canonical Run inspection tests pass; Goal routes call `list_goal_views`/`goal_view`, which consume the shared inspection seam. UI uses existing `/dag-runs` navigation. Browser control path UNVERIFIED this round. |
| 2 | Canonical Goal/Agent/Run/Event reads | PARTIAL: scoped reader and membership tests pass. `goal_inspection.py:388` discovers Goals only from retained Conductor projections; Goals without retained Run evidence remain absent. Canonical Event and Agent inspection end-to-end UNVERIFIED. |
| 3 | Exact revision, intent, owner, reconciliation, lineage | PARTIAL: new red-to-green regressions at `test_goal_inspection.py:456,488` prevent wrong-revision/stale condition display; existing revision, parentage and graph tests pass. `goal_inspection.py:355` still derives disposition from Run status, not canonical reconciliation/blocker. |
| 4 | One Goal with sequential/concurrent Runs | `test_sequential_runs_form_one_goal_history` passes with completed and active evidence grouped once. Production Goal-bound concurrent admission/UI UNVERIFIED. |
| 5 | Run terminality never determines Goal terminality | Completed/failed Run and canonical Goal-state tests pass; production projection reads Goal status only from its owner. Browser rendering UNVERIFIED this round. |
| 6 | Preserve canonical Run identity/status/control | `test_run_identity_and_status_are_the_run_seams_truth` and canonical Run inspection/control suite pass; no repair touches IDs, lifecycle or controls. |
| 7 | Restart/reconnect survives | UNVERIFIED. Existing `test_projection_persists_nothing` proves repeated reads/no writes, not a process restart. No durable Goal-to-UI reconnect test executed. |
| 8 | Retry/replan/child/delegation/HITL provenance | PARTIAL: existing seeded provenance/child Run tests pass. They do not prove those producers stamp the facts in the production Goal path. |
| 9 | Distinguishable waiting/blocked/suspended/stopping/terminal states | PARTIAL: paused/waiting and failed/terminal tests pass. Reconciliation suspended/stopping reasons and owner-driven UI coverage UNVERIFIED. |
| 10 | Trace failures and security/approval to execution and reconciliation | NOT MET: canonical-only detail (`dag_run_inspection.py:348`) serves empty Events and no Invocation/effect/approval links; no reconciliation decision is consumed. |
| 11 | Goal → Graph/Run → Attempt/effect/artifact and back | PARTIAL: canonical NodeRun/Attempt and creative artifact inspection tests pass. Effects are absent; canonical-only Goal backlink cannot discover a Goal absent from the retained projection window. Browser roundtrip UNVERIFIED. |
| 12 | Canonical product language | NOT MET: `frontend/src/pages/DagRuns.tsx:211` still renders `Live DAG Runs`. No cosmetic-only change made. |
| 13 | No new dashboard store/runtime | Existing read-only route and projection-no-write tests pass; inspection remains a projection over existing stores. This repair adds no store/runtime/authorization or scheduler. |

## Commands and results

All Python validation used `uv run`; command timeouts were 1,000 seconds.

- `uv sync --locked --extra dev`: pass.
- `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -q -k 'legacy_goal_facts_do_not_cross_revision_boundaries or canonical_empty_conditions_override_legacy_provenance'`: **2 expected failures before fix**, both on stale values, not setup errors.
- `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py packages/hive-conductor/backend/tests/test_canonical_run_inspection.py packages/hive-conductor/backend/tests/test_dag_run_creative_inspection.py -x -q`: 37 passed before test addition, 39 passed after fix.
- `uv run pytest packages/maistro-core/tests/runs/test_goal_context.py -x -q`: 6 passed.
- `uv run pytest packages/hive-conductor/backend/tests -x -q`: 3,753 passed, 19 skipped.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3,330 files already formatted.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`: pass, 3,772 collected.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, 16,469 collected.
- `uv run python scripts/check-route-permissions.py`: pass.
- `uv run python scripts/check-frontend-api-routes.py`: pass.
- `uv run python scripts/check-api-route-contracts.py`: pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: pass before and after repair; no ledger/grant edit warranted.
- Frontend TypeScript checks above: pass.
- `git diff --check`: pass.

## Handoff

Changed files: `backend/services/goal_inspection.py` and
`backend/tests/test_goal_inspection.py` under `packages/hive-conductor`, plus this
report and `docs/testing/inventory-notes/auto-65-exact-revision-facts.md`.

Verdict: **NEEDS-REPAIR**, despite green validation for the focused fix. Do not
interpret this commit as integration approval. The supplied prior blocker was
not a current vulture failure. Completing #65 still requires reachable
Goal-driven admission/discovery, canonical reconciliation evidence, and governed
effect/approval navigation plus real restart/browser coverage. Do not synthesize
these facts in Conductor or invent Goals for arbitrary Runs to satisfy tests.

Snapshot progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#65 structural acceptance gaps; focused revision-integrity repair complete"}`.

