# Issue #65 CI repair checkpoint

## Frozen scope

- Writer lane: issue #65 only; branch `auto-65`, worktree `/home/dev/Git/wt/auto-65`.
- Verified starting HEAD `d07a7e501210110a13e0892b37d6d7fbbd350fa9`; supplied base `d8675ac8933c21db141db0bc42584404474b44b3` resolves. Initial worktree clean.
- Frozen evidence: supplied `dispatch-context.json`, prior job result if present, existing issue-65 repair notes and changed production/tests, relevant repository instructions/ADRs, and local validation.
- Explicit repair target: exact-debt-ledger vulture command specified in lane. Only evidenced dead code or reviewed retained identities will be repaired; `quality/vulture-baseline.json` amendment is explicitly allowed for this round. No other ledger/grant edits.
- Candidate edits: this report, vulture baseline, and only issue-65 production/test/inventory files implicated by executed checks. No additional issues/PRs will be enumerated or fetched.
- Ambiguity: dispatch includes historical findings as well as a CI-repair assignment. Treat findings as claims to verify against current HEAD, not instructions to rewrite already repaired behavior. Report any remaining acceptance gaps truthfully.
- Job directory initially contains no `check-*.log` files; run validation locally rather than infer prior success.

## Progress

- Loaded exact issue acceptance criteria from frozen dispatch. Inspected initial diff summary; no pre-existing uncommitted changes to salvage.
- `uv sync --locked --extra dev` passed. Prescribed vulture scan passed against base `d8675ac8933c`: 1,322 findings / 1,322 reviewed identities, zero unclassified. No ledger edit justified.
- Read repository instructions, previous repair reports and prior verifier artifact. Those are historical claims, not fresh acceptance proof. Current source confirms the historical discovery/reconciliation/Event/effect gaps still exist: `goal_inspection.py` discovers via `list_visible_runs`, derives disposition from Run statuses, and canonical-only details have empty Events. These will not be papered over by a new product-private authority.
- Read accepted ADR-081226-9944, ADR-082826-b601 and ADR-082826-d9f5. Preserve canonical ownership and the reviewed standalone projection fallback.
- Found a bounded adjacent defect in issue-65's added NodeRun/Attempt projection: `visible_run_detail` attaches children from a cross-Workspace canonical link even when `_overlay` rejects that same link. Membership in both Workspaces does not make the children evidence of the displayed Run. Selected repair within frozen file scope: reproduce through existing HTTP cross-link tests in `test_goal_inspection.py`, guard child evidence in `dag_run_inspection.py`, and record inventory delta. This is an attribution-integrity defect, not a claim of unauthorized disclosure to a member of both Workspaces.
- Regression reproduced before production repair: `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -q -k cross_workspace_run_link_cannot_relocate_a_goal` -> 1 failed (member of both received `node_runs` under corrupt projection), 1 passed (foreign Workspace). Added real NodeRun/Attempt and legitimate-path assertions to existing test cases; collected-test delta is zero.
- Repair: child evidence now checks the canonical Run's immutable Workspace against the displayed record through the existing scoped reader. No new authorization/store/runtime; rejected or unreadable evidence remains absent rather than fabricated as empty. Post-fix focused tests passed (47). Root Ruff check/format passed (3,332 files).
- Full Conductor backend run passed: 3,755 passed, 19 skipped, 30 warnings in 187.09s. Warnings concern audit/model serialization and deprecated per-request test-client cookies, not this regression. Skips are not acceptance evidence.
- Gates passed: suite inventory (Conductor 3,774; core 16,495, no duplicate evidence); route permissions (41 prefixes); typed frontend client (no new debt); frontend API routes (185 sites); API route contracts (296 handlers); repeated exact vulture (1,322 reviewed identities/findings). No ledger or grant edits.

## Acceptance audit (frozen issue-body order)

The 47-test focused run and full backend run execute production inspection
services/routes against real canonical in-memory stores and scoped readers.
Most Goal fixtures seed projection rows; this does not prove discovery without
those rows or persistent producer-to-browser integration. Browser tests at
`packages/hive-conductor/tests/e2e/goal-run-roundtrip.spec.ts:174-199` stub Goal
and Run HTTP responses. They were inspected, not executed this round.

| # | Criterion | Executed evidence / remaining gap |
|---|---|---|
| 1 | Consume #1036 inspection/control APIs | PARTIAL: shared Run inspection/control tests pass; Goals navigates to the existing Run API surface. Browser control path UNVERIFIED; `DagRuns.tsx:157-167,468` still derives legacy activity sketch state locally (not by itself proof of a competing execution authority). |
| 2 | Canonical Goal/Agent/Run/Event reads | NOT MET: `goal_inspection.py:390` discovers only retained projection rows; canonical-only detail is readable but cannot enter the Goal history. Scoped readers have no public discovery method. Canonical Events remain absent (`dag_run_inspection.py:356`); canonical Agent inspection UNVERIFIED. |
| 3 | Exact revision, accountability, intent, reconciliation, subgoals, Graphs, Runs | PARTIAL: exact-revision, conditions, lineage and Graph tests pass. `goal_inspection.py:355` derives disposition from Run statuses, not canonical reconciliation decisions/reasons. Accountable Agent is displayed as an ID only. |
| 4 | One history for sequential/concurrent Runs | PARTIAL: `test_sequential_runs_form_one_goal_history` and retry/child history tests pass. Concurrent producer-to-browser behavior UNVERIFIED. |
| 5 | Terminal Run cannot terminalize Goal | VERIFIED at production projection boundary: completed/failed evidence and canonical Goal-state tests pass; `Goals.tsx` renders Goal outcome separately from execution disposition. Browser behavior UNVERIFIED. |
| 6 | Canonical Run identity/status/control parity | PARTIAL: shared inspection/cancellation tests and identity/status parity test pass. Strengthened HTTP regression now excludes wrong-Workspace physical evidence while preserving exact child identities on legitimate projection and canonical-id paths. Browser controls UNVERIFIED. |
| 7 | Restart/reconnect survival | UNVERIFIED end to end. `test_projection_persists_nothing` compares two reads in one process; it is not restart proof despite its docstring. No process-restart/browser workflow executed. |
| 8 | Retry/replan/child/delegation/HITL provenance | PARTIAL: seeded provenance and real child-Run lineage tests pass; frontend displays recorded provenance. Complete producer stamping and canonical HITL decision/reason inspection UNVERIFIED. |
| 9 | Distinguishable waiting/blocked/suspended/stopping/terminal states | PARTIAL: paused/waiting/failed/cancelled execution tests pass. Canonical reconciliation state/reasons are not read; suspended/stopping product behavior UNVERIFIED. No new lifecycle states invented. |
| 10 | Trace failure/security/approval to execution and reconciliation | NOT MET: `dag_run_inspection.py:220-284` projects NodeRuns/Attempts but no Invocation/effect/approval evidence; no reconciliation decision join. |
| 11 | Goal -> Graph/Run -> Attempt/effect/artifact and back | PARTIAL: canonical child evidence and creative-artifact tests pass, including repaired attribution. Effects absent and projectionless Goal backlink has no discovery target. Production browser roundtrip UNVERIFIED. |
| 12 | Canonical user-facing language | NOT MET: `DagRuns.tsx:211` still says `Live DAG Runs`; backend package vocabulary also remains in the activity description. No cosmetic-only repair substituted for missing behavior. |
| 13 | No separate dashboard store/runtime | VERIFIED for this repair: reads through the existing scoped owner, no new store, execution/Goal/event authority, scheduler or authorization path. No-write test passes; full shared Goal-centric product experience remains incomplete. |

## Executed validation

All commands ran in the assigned worktree, with 1,000-second timeouts.

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed before and after repair, 1,322/1,322. No unbanked identities to amend.
- `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -q -k cross_workspace_run_link_cannot_relocate_a_goal`: expected pre-fix failure (1 failed, 1 passed), wrong-Workspace child attribution at line 1088.
- `uv run ruff format packages/hive-conductor/backend/services/dag_run_inspection.py packages/hive-conductor/backend/tests/test_goal_inspection.py`: formatted changed blocks.
- `uv run pytest packages/maistro-core/tests/runs/test_goal_context.py packages/hive-conductor/backend/tests/test_goal_inspection.py packages/hive-conductor/backend/tests/test_canonical_run_inspection.py packages/hive-conductor/backend/tests/test_dag_run_creative_inspection.py -x -q`: 47 passed.
- `uv run pytest packages/hive-conductor/backend/tests -x -q`: 3,755 passed, 19 skipped, 30 warnings (187.09s).
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,332 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests`: passed, 3,774 / 16,495 collected. Core collection is not full core test execution.
- `uv run python scripts/check-route-permissions.py`: passed, 41 prefixes, zero undeclared.
- `uv run python scripts/check-frontend-typed-client.py`: passed, no new debt.
- `uv run python scripts/check-frontend-api-routes.py`: passed, 185 call sites.
- `uv run python scripts/check-api-route-contracts.py`: passed, 296 handlers.
- `git diff --check` and `git diff --check d8675ac8933c21db141db0bc42584404474b44b3`: passed.

## Handoff

Changed files:

- `packages/hive-conductor/backend/services/dag_run_inspection.py`: scoped physical-evidence attribution guard.
- `packages/hive-conductor/backend/tests/test_goal_inspection.py`: strengthened real-HTTP regression and positive controls.
- `docs/testing/inventory-notes/auto-65-child-evidence-scope.md`: zero collection delta; meaningful assertion additions.
- `docs/testing/auto-65-ci-repair.md`: this report.

**NEEDS-REPAIR** for issue #65 as a whole. The focused physical-evidence repair
is complete and validation passes; broader canonical discovery,
reconciliation/reason inspection, Event/Invocation/effect/approval navigation,
and production restart/browser evidence remain unresolved. The earlier
validation-budget marker is not the substantive blocker. This repair adds one
scoped Run lookup per detail evidence read; no performance bound is claimed.
No sync conflict, remote mutation, ledger/grant edit, or integration approval.

Snapshot progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#65 owner-seam/product acceptance gaps; focused attribution repair complete"}`.
