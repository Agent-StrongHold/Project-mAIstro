# Issue 65 repair checkpoint

Frozen scope: issue #65 only; supplied dispatch snapshot and starting HEAD 54149cf347439bdbd01cd302c9fafb6c922aea35 on auto-65. Clean worktree verified at start. No remote mutations or re-enumeration.

Assigned CI repair: execute exact vulture scan, review reported identities, amend only the permitted vulture ledger where warranted; run focused acceptance validation. Candidate files: quality/vulture-baseline.json; issue-65-repair-notes.md; production/test files only if actual scan evidence requires correction (record exact paths before editing).

Ambiguity: dispatch combines broad product repair with explicit CI-repair instructions. Proceed with the explicit evidence-driven vulture repair first, and report any unproven product acceptance rather than inventing new authorities. No check-*.log files present in supplied job directory at start.

Status: exact vulture scan executed successfully after `uv sync --locked --extra dev`: 1,322 findings / 1,322 reviewed identities; zero unbanked. No ledger amendment justified. Prior result artifact and previous repair notes inspected as evidence only. Frozen issue acceptance list has 13 criteria; audit below will distinguish executed coverage from missing production behavior.

Focused validation: root Ruff check and format check passed (3,330 formatted files); core Goal-context plus Conductor Goal/canonical-Run/creative inspection tests passed (47 tests). Source confirms Goal discovery calls projection-backed `list_visible_runs`, reconciliation is Run-status-derived, and canonical-only details have empty Events. The guessed ADR filename `ADR-081226-9944-agent-goal-graph-ontology.md` was not found; skipped. Resolve the actual filename before further reads. No production or test edits justified by the passing vulture scan; no new test inventory delta.

Full Conductor backend validation passed: 3,755 passed, 19 skipped, 30 warnings in 188.94 seconds. Warnings were audit/model Pydantic serialization and deprecated per-request test-client cookies. Skips are not acceptance evidence. Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-082826-b601 and ADR-082826-d9f5. Reconciliation: use canonical owner seams; do not substitute a Conductor discovery store or infer reconciliation decisions from physical execution outcomes. Existing frontend roundtrip tests stub Goal/Run HTTP doors and cannot establish production owner-to-browser reachability even if they pass. No browser or process-restart test executed.

Additional gates passed: suite inventory (Conductor 3,774; core 16,469; no duplicate evidence), route permissions (41 prefixes; none undeclared), frontend API routes (185 call sites), API route contracts (296 handlers). Base-to-HEAD whitespace check passed. An inline production-route discovery probe initially failed with HTTP 401 because its fabricated Request omitted the canonical principal; this is probe setup failure, not an acceptance failure. The corrected attempt used `Principal(user_id=..., username=...)` as the existing cancellation-route test does. It PASSED its reproduction assertions: create a real canonical Goal and bound Run using the existing `_make_scene` in-memory canonical stores; `visible_run_detail` returns the Run and exact Goal binding; production `list_goals` returns `[]`; production `get_goal` raises HTTP 404. No projection row was seeded. This confirms a reachable handler defect, not a browser or persistence proof.

## Acceptance audit (frozen issue-body order)

All test references below were executed in the focused 47-test run and/or the full Conductor package run. Existing Goal fixtures seed Conductor projection rows; passing them cannot prove projection-independent discovery.

| # | Criterion | Executed evidence / remaining gap |
|---|---|---|
| 1 | Consume #1036 shared inspection/control seam | PARTIAL: shared canonical inspection/control tests passed; `goal_inspection.py:390` calls that seam. Browser control acceptance UNVERIFIED; `DagRuns.tsx:157` still derives node state from local events. |
| 2 | Canonical Goal/Agent/Run/Event reads | NOT MET: corrected production-handler probe reproduces empty Goal list and 404 despite readable canonical Goal-bound Run. Agent identity is only an ID field; canonical Event inspection absent at `dag_run_inspection.py:348`. |
| 3 | Exact revision, accountability, intent, reconciliation, Subgoals, Graphs, Runs | PARTIAL: revision/conditions/parentage/Graph tests pass. `goal_inspection.py:355` obtains disposition from Run statuses, not a reconciliation decision or waiting reason. |
| 4 | One history for sequential/concurrent Runs | PARTIAL: `test_sequential_runs_form_one_goal_history` and retry/child history tests pass. Concurrent producer-to-browser behavior UNVERIFIED. |
| 5 | Terminal Run cannot silently terminalize Goal | VERIFIED at production projection/route boundary: completed/failed evidence and canonical Goal-state tests pass. Goal state reads the canonical Goal, independent of Run disposition. Browser behavior UNVERIFIED. |
| 6 | Canonical Run identity/status/control parity | PARTIAL: shared seam identity/status and cancellation tests pass; no identity changes in this round. Browser control path UNVERIFIED. |
| 7 | Restart/reconnect | UNVERIFIED end to end. `test_projection_persists_nothing` only compares two reads in one process, not restart/reconnect. Projectionless handler probe demonstrates a missing history path independently of persistence. |
| 8 | Retry/replan/child/delegation/HITL provenance | PARTIAL: seeded provenance and child/Attempt tests pass. Full production producer stamping and browser workflow UNVERIFIED. |
| 9 | Waiting/blocked/suspended/stopping/terminal distinctions | PARTIAL: waiting-human, failed and terminal Run evidence tests pass. Canonical reconciliation reasons/suspended/stopping presentation UNVERIFIED; no new lifecycle states invented. |
| 10 | Failure/security/approval -> execution and reconciliation decision | NOT MET: `dag_run_inspection.py:220-262` reads NodeRuns/Attempts only, no Invocation/effect/approval decision join; `goal_inspection.py:355` lacks reconciliation decision evidence. |
| 11 | Goal -> Graph/Run -> Attempt/effect/artifact -> back | NOT MET: NodeRun/Attempt and creative-artifact tests pass, but effects absent; corrected probe confirms a canonical-only Run's Goal backlink has no Goal target. Browser navigation UNVERIFIED. |
| 12 | Canonical product language | NOT MET: `DagRuns.tsx:211` renders `Live DAG Runs`; a label-only repair would not fix the missing behavior. |
| 13 | No competing dashboard store/runtime | No new store/runtime/authority introduced this round (notes-only diff). Existing Goal no-write test passes. Local event-derived frontend node presentation remains at `DagRuns.tsx:466`; this alone is not evidence of a second authoritative scheduler. Full shared Goal-centric product acceptance remains incomplete. |

## Executed commands

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1,322 / 1,322 identities; default ratchet merge base reported `35a72ff54d4f`.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,330 files.
- `uv run pytest packages/maistro-core/tests/runs/test_goal_context.py packages/hive-conductor/backend/tests/test_goal_inspection.py packages/hive-conductor/backend/tests/test_canonical_run_inspection.py packages/hive-conductor/backend/tests/test_dag_run_creative_inspection.py -x -q`: 47 passed.
- `uv run pytest packages/hive-conductor/backend/tests -x -q`: 3,755 passed, 19 skipped, 30 warnings.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`: passed, 3,774.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16,469 (collection only, not core full-suite execution).
- `uv run python scripts/check-route-permissions.py`: passed, 41 declared prefixes.
- `uv run python scripts/check-frontend-api-routes.py`: passed, 185 call sites.
- `uv run python scripts/check-api-route-contracts.py`: passed, 296 handlers.
- `git diff --check d8675ac8933c21db141db0bc42584404474b44b3`: passed.
- Inline `uv run python` canonical-only discovery probe: first attempt HTTP 401 setup error; corrected canonical principal reproduced empty Goal list and Goal-detail 404.

## Handoff

Only changed file this round: `issue-65-repair-notes.md`. No test additions, inventory delta, production code, ledger or grant changes. Passing scanner evidence does not justify a fabricated ledger amendment. No sync conflict existed; no fetch/merge performed.

**NEEDS-REPAIR**: unresolved work is canonical discovery, reconciliation decision/reason inspection, Event/Invocation/effect/approval inspection, and production-to-browser restart/navigation evidence. These require owner-seam implementation, not a second Conductor index, lifecycle, or authorization path. This round completed fresh validation and a concrete defect reproduction, not the product repair. The previous validation-budget marker is not the substantive blocker.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#65 owner-seam and product acceptance repair"}`. One probe setup error was corrected as documented above. Commit this handoff locally; do not integrate or close the issue.
