# Issue #65 repair round

## Frozen scope

- Issue: #65 only; branch/worktree: `auto-65`.
- Starting HEAD: `96a434fbf6119cb96a41671f011bad637d7bb23c`.
- Develop base: `35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`.
- Existing implementation files: Goal/Run inspection services/routes, associated
  frontend pages and tests, core Run Goal context, and their inventory notes.
- Additional explicit CI-repair scope: `quality/vulture-baseline.json`, only
  for identities actually reported by the prescribed scan.
- Review input: frozen dispatch-context.json from job
  `559894e4f74b4766916ff2f627ce2473`; no GitHub mutations or re-fetches.

## Initial evidence

- Working tree clean; exact starting HEAD confirmed.
- Job directory has no `check-*.log` files. Validation will run locally.
- Acceptance is the 13-item issue-body list in the supplied dispatch snapshot.
- Prior findings are hypotheses to check against this HEAD, not assumed facts.
- A broad parent-directory instruction search timed out without results;
  subsequent inspection is scoped to this worktree.

## Results

- Prescribed vulture scan PASSED: 1,322 reviewed identities, 1,322 findings,
  no unbanked identities. No ledger amendment is justified.
- Base-to-HEAD whitespace check reproduced the prior failure at
  `auto-65-repair-validation.md:18,19,79`.
- Source review confirms projection-gated Goal discovery, Run-derived execution
  disposition, and absent canonical Event/effect/approval inspection. These are
  real acceptance gaps, not vulture findings.
- Prior result artifact inspected; its successful checks are not reused as
  current validation evidence.
- Read accepted ADR-081226-9944 and ADR-082826-d9f5. Reconciliation:
  inspection may project existing canonical records, not mint a second Goal,
  execution, or authorization authority to bypass missing discovery APIs.
- Confirmed `ScopedGoalStore` and `ScopedRunReader` have only by-ID reads,
  not canonical discovery. Full discovery requires owner-seam work, not a
  Conductor-private scan/index. Reconciliation/effect UI work remains unresolved.
- A guessed agents reconciliation glob was not found; skipped, not retried.
- Selected bounded repair: reproduce and reject cross-Workspace canonical
  links during Goal grouping. The Run overlay already rejects those links,
  but Goal grouping currently joins them without checking Workspace identity.
  Also correct the reproduced whitespace-check failure. Broader acceptance
  remains incomplete; do not label a focused repair MERGE-READY.
- Regression reproduced through HTTP before fixing production code: the
  member-of-both case failed because the wrong Workspace's Goal list contained
  canonical Goal state. The foreign-Workspace case passed (existing boundary).
- Added the same Workspace-identity guard already used by the shared Run
  overlay, without changing membership, Run status, identity or control.
- After repair: 41 focused Conductor inspection tests and 6 core Goal-context
  tests passed. Root Ruff check/format and working diff whitespace check passed.
- Suite inventory passed with 3,774 Conductor tests (+2 from this repair);
  route permissions, frontend API routes, and API route contracts passed.
- Full Conductor package validation PASSED: 3,755 passed, 19 skipped,
  30 warnings in 195.35 seconds. Warnings concern audit/model serialization and
  deprecated test-client cookie usage; no failures. Skips are not acceptance
  evidence.

## Commands executed this round

All Python execution used `uv run`; test/gate timeouts were 1,000 seconds
(the first vulture scan used 600 seconds).

- `uv sync --locked --extra dev`: passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py packages/hive-conductor/backend/tests/test_canonical_run_inspection.py packages/hive-conductor/backend/tests/test_dag_run_creative_inspection.py -x -q`:
  39 passed before additions; 41 passed after repair.
- `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -q -k cross_workspace_run_link_cannot_relocate_a_goal`:
  before repair, 1 expected failure on wrong-scope Goal data, 1 passed.
- `uv run pytest packages/maistro-core/tests/runs/test_goal_context.py -x -q`:
  6 passed.
- `uv run pytest packages/hive-conductor/backend/tests -x -q`:
  3,755 passed, 19 skipped.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed; 3,330 files already formatted.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`:
  passed; 3,774 collected, no duplicate evidence.
- `uv run python scripts/check-route-permissions.py`: passed; 41 prefixes,
  zero undeclared.
- `uv run python scripts/check-frontend-api-routes.py`: passed; 185 call sites.
- `uv run python scripts/check-api-route-contracts.py`: passed; 296 handlers.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed; 1,322 reviewed identities / findings. No ledger or grant changed.
- `git diff --check` and `git diff --check 35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`:
  passed after the whitespace repair (including the full base-to-working-tree delta).
- `uv run python scripts/check-doc-links.py`: passed; 2,416 Markdown files,
  zero broken relative links.
- Repeated the exact vulture scan after repair: passed, unchanged 1,322 identities.
- Initial staged whitespace check caught an extra EOF blank line in this new
  audit note; removed it before committing. No production changes resulted.

## Acceptance audit (issue body order)

The HTTP regression tests use production routes and real in-memory canonical
stores/readers, but seeded projection rows. They prove the read boundary, not
complete producer-to-browser integration. No browser or process restart test was
executed in this round.

| # | Criterion | Evidence and remaining limitation |
|---|---|---|
| 1 | Consume #1036 inspection/control seam | PARTIAL: Goal HTTP and canonical Run inspection/control tests pass in the full package run. UI reads the shared routes, but `DagRuns.tsx:157` still reconstructs local event/node state. Browser control behavior UNVERIFIED. |
| 2 | Canonical Goal/Agent/Run/Event reads | PARTIAL: scoped Goal/Run tests pass; new HTTP regression rejects cross-Workspace attribution. `goal_inspection.py:390` still discovers only retained projection evidence; canonical Event and Agent inspection UNVERIFIED. |
| 3 | Revision, accountability, intent, reconciliation, subgoals, Graphs, Runs | PARTIAL: exact-revision, condition, parentage and Graph tests pass. `goal_inspection.py:355` reads execution disposition from Run status, not a reconciliation decision. |
| 4 | One Goal history for sequential/concurrent Runs | PARTIAL: `test_sequential_runs_form_one_goal_history` and child/retry history tests pass. Concurrent production admission to UI UNVERIFIED. |
| 5 | Terminal Run does not terminalize Goal | VERIFIED at production projection/HTTP boundary: completed/failed evidence tests and canonical Goal-state test pass. Goal outcome is read only from the scoped Goal owner. |
| 6 | Preserve shared canonical Run identity/status/control | PARTIAL: identity/status parity, cancellation and canonical-only detail tests pass. New wrong-scope test verifies Goal joining honors the existing overlay boundary. Browser controls UNVERIFIED. |
| 7 | Live/historical views survive restart/reconnect | UNVERIFIED end to end. Full package includes retained Run durability tests, but repeated stateless Goal reads do not establish a durable Goal-to-browser restart workflow. |
| 8 | Retry/replan/child/delegation/HITL provenance visible | PARTIAL: seeded provenance and real child-Run lineage tests pass. Complete production producer stamping and browser display UNVERIFIED. |
| 9 | Waiting/blocked/suspended/stopping/terminal states distinguished | PARTIAL: Run paused/waiting/failed/cancelled tests pass. Reconciliation disposition/reasons and suspended/stopping presentation UNVERIFIED. |
| 10 | Trace failure/security/approval to execution and reconciliation | NOT MET: `dag_run_inspection.py:236` projects NodeRuns/Attempts but no Invocation/effect/approval evidence; canonical-only detail returns empty Events at line 348. No reconciliation decision join. |
| 11 | Goal to Graph/Run to Attempt/effect/artifact and back | PARTIAL: NodeRun/Attempt and creative-artifact tests pass. Effects absent; projectionless Goal backlink cannot discover its target; browser roundtrip UNVERIFIED. |
| 12 | Canonical user-facing language | NOT MET: `DagRuns.tsx:211` still says `Live DAG Runs`; no cosmetic-only fix substituted for the missing behavior. |
| 13 | No separate dashboard store/runtime | VERIFIED for this repair: production source and no-write tests confirm read-time projection only; no new scheduler, store, lifecycle or authorization authority. |

## Handoff

Changed files this round:

- `packages/hive-conductor/backend/services/goal_inspection.py`
- `packages/hive-conductor/backend/tests/test_goal_inspection.py`
- `docs/testing/inventory-notes/auto-65-goal-scope-integrity.md`
- `docs/testing/auto-65-repair-validation.md` (reproduced whitespace failure only)
- `docs/testing/auto-65-repair-round.md` (this audit)

Verdict: **NEEDS-REPAIR**. This bounded scope-integrity repair does not resolve
canonical discovery, reconciliation/decision/effect inspection, frontend local
event reconstruction, or complete restart/browser acceptance. No claim that
validation budget alone was the blocker remains: the substantive gaps above
are still present in reachable production code. Owner-level discovery and
inspection seams must be completed rather than worked around in Conductor.

Snapshot progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#65 structural acceptance gaps; focused scope-integrity repair complete"}`.
