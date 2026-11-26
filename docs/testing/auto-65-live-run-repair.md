# Issue 65 — live Run inspection repair (2026-10-19)

## Frozen scope and disposition

Assigned issue: #65 only, branch `auto-65`, starting HEAD
`bc8812304b8b4d238cd83c8bd9a66ee741ff0d22`, supplied develop base
`e708451b3887c8a1540d5b7a3eefe827ac0755df`. The worktree started clean.
The dispatch snapshot and previous result were read locally; no remote issue or
PR lists were refreshed and no GitHub mutations were performed. The current job
had no `check-*.log` files; validation below was executed afresh.

**NEEDS-REPAIR: partial implementation, not integration approval.**
Issue progress: checked 1, completed 0, skipped 0. Next: canonical discovery and
reconciliation/decision inspection capabilities, followed by producer-to-browser
acceptance coverage. These are unresolved, not claimed complete by passing tests.

## Actual repair and files

- `packages/hive-conductor/frontend/src/pages/DagRuns.tsx`: re-read the shared
  `/v1/dag-runs/{id}` seam every ten seconds and on stream open/reconnect or
  resync. Serialize reads and discard late responses after deselection. Clean
  up the timer and stream; a failed initial read can recover on the next tick.
  Keep failed refreshes visibly stale, then clear the warning after recovery.
  Render the seam's status verbatim and expose a differing canonical ID rather
  than translating it. Show the legacy fixed topology only when legacy events
  exist, not as a fictional Graph for canonical-only Runs. Heading is `Runs`.
- `packages/hive-conductor/tests/e2e/goal-run-roundtrip.spec.ts`: three added
  regressions (polling, reconnect/resync, deselection race); fixtures now carry
  status and canonical ID. Tests use the browser clock, not elapsed-time bounds.
- `packages/hive-conductor/tests/e2e/navigation-coverage.spec.ts`: existing
  navigation assertion follows the renamed heading.
- `docs/testing/inventory-notes/auto-65-live-run-refresh.md`: zero pytest delta;
  three additional Playwright cases, which that inventory does not collect.
- This report.

The three new browser cases were each run against the unchanged production
component before repair. They failed respectively on a stale `running` Attempt
instead of `completed`, stale evidence after reconnect instead of `yielded`, and
extra open streams for the deselected Run. All pass after repair. This is not a
cosmetic-only change or a guessed scanner finding.

## Architecture reconciliation

Read repository instructions and Accepted ADRs `ADR-081226-9944` (hierarchy),
`ADR-081226-a66b` (Run/NodeRun/Attempt lifecycle), and `ADR-081226-7248`
(durable Events). Canonical status is read, never inferred from delivery events.
There is no new store, execution authority, authorization path, or scheduler.
The browser timer only refreshes inspection and does not execute work.

The exact requested vulture gate passed **before any edit**: 1321 reviewed
identities, 1321 findings, zero unclassified. No dead identity was demonstrated,
so no speculative code removal or ledger amendment is warranted. No quality
ledger or grant was edited. The gate reports its trusted merge base as
`e0cca7024ef7`; the supplied develop comparison base is recorded above, not
silently substituted for the gate's provenance selection.

Canonical discovery cannot be repaired by scanning a private store here:
`ScopedRunReader` exposes by-ID and child reads, not a recent Run/Goal query;
`dag_run_inspection.py:309-332` explicitly retains projection-gated discovery.
Likewise the canonical Goal reader has no reconciliation-disposition API. The
issue's richer requirements do not authorize a competing discovery store,
reconciliation authority, or event sequence. Those gaps remain explicit.

## Commands and executed outcomes

All commands ran in the assigned worktree with long timeouts. Logs/config are
under job `ab973b1959f14d4b838b5430c4f5e279` in `/home/dev/maistro/jobs/`.

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed unchanged (1321/1321).
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3333 files already formatted.
- `uv run pytest packages/maistro-core/tests/runs/test_goal_context.py packages/hive-conductor/backend/tests/test_goal_inspection.py packages/hive-conductor/backend/tests/test_dag_run_canonical_lifecycle.py packages/hive-conductor/backend/tests/test_dag_run_scope.py packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py packages/hive-conductor/backend/tests/test_dag_run_history_durability.py -x -q`: **127 passed**.
- From `packages/hive-conductor/frontend`, `npm run build`: passed.
- From the same directory, `npx eslint src/pages/DagRuns.tsx`: passed.
- `uv run python scripts/check-frontend-typed-client.py`: passed, no new debt.
- `uv run python scripts/check-route-permissions.py`: passed, 41 declared prefixes.
- `uv run python scripts/check-suite-inventory.py --suite <suite>` for each of
  `packages/hive-conductor/tests/e2e` (23),
  `packages/hive-conductor/backend/tests` (3774), and
  `packages/maistro-core/tests` (16495): all passed.
- `NODE_PATH="$PWD/packages/hive-conductor/frontend/node_modules" packages/hive-conductor/frontend/node_modules/.bin/playwright test --config=/home/dev/maistro/jobs/ab973b1959f14d4b838b5430c4f5e279/playwright-repair.config.cjs goal-run-roundtrip.spec.ts`: **10 passed**.
- Same Playwright command with `navigation-coverage.spec.ts dag-run-button-truthfulness.spec.ts`: **22 passed**.
- `git diff --check`: passed.

The job-local Playwright config uses a harness-managed Vite server on port 5178
serving this worktree and proxying to the already available backend on 8101.
It uses Chromium, one worker, no retries. No backend was restarted by this round.
The first browser invocation failed module resolution before collecting tests;
setting `NODE_PATH` to the existing frontend dependencies resolved that harness
problem. The subsequent pre-fix failures were actual assertions described above.

## Acceptance matrix (issue checklist order)

| # | Criterion | Evidence / remaining gap |
|---|---|---|
| 1 | Consume shared #1036 inspection/control seam | UI uses `/v1/dag-runs`; backend scope/cancel tests pass. Partial: no production browser-to-control round trip was executed. |
| 2 | Canonical Goal/Agent/Run/Event sources | Canonical Goal and Run reads covered by `test_goal_inspection.py`; no canonical Event inspection or Agent-reader integration. NOT MET. |
| 3 | Complete Goal view including reconciliation | Exact revision/intent, agent ID, graphs/subgoals tests pass. `goal_inspection.py:113-151` derives execution disposition/blocker from Runs, not reconciliation. NOT MET. |
| 4 | One Goal history for sequential/concurrent Runs | Grouping test and browser two-Run case pass for retained projection rows. Canonical-only discovery absent. Partial. |
| 5 | Run terminal outcome cannot decide Goal outcome | `test_completed_runs_do_not_render_the_goal_completed`, `test_canonical_goal_state_and_bound_revision_are_not_derived_from_a_run`, and browser outcome case pass. Verified for inspected seam. |
| 6 | Canonical identity/status/control parity | `test_run_identity_and_status_are_the_run_seams_truth`, canonical lifecycle/cancel tests pass; UI now displays returned status and refreshes it. Production browser control remains UNVERIFIED. |
| 7 | Restart/reconnect survival | New reconnect/resync browser test passes; projection durability unit tests pass. Full canonical Goal/Run process restart is UNVERIFIED; browser tests use fixtures. |
| 8 | Retry/replan/child/delegation/HITL provenance | Seeded backend retry/child/delegation/HITL tests pass. Production producer-to-browser provenance and replan remain UNVERIFIED. |
| 9 | Distinguishable human/blocked/suspended/stopping/terminal | Paused/waiting/failure tests pass, UI relays status unchanged. No reconciliation suspended/stopping state is read. Partial. |
| 10 | Failure/security/approval to physical and reconciliation trace | `dag_run_inspection.py:220-276` exposes children; `:335-348` leaves canonical-only Events empty. Invocation/effect/approval/reconciliation trace is absent. NOT MET. |
| 11 | Goal -> Graph/Run -> Attempt/effect/artifact and back | Browser navigation and physical child tests pass for reachable rows. Effects and canonical-only Goal discovery remain missing; full artifact route UNVERIFIED. |
| 12 | Canonical user concepts instead of backend names | Heading now `Runs`, unrelated demo sketch removed. `AppShell.tsx:46` still says `DAG Runs`; broad concept migration remains incomplete. |
| 13 | No separate dashboard store/runtime | Read-only projection test passes; repair only re-reads the existing shared API. Verified by inspected diff and tests. |

Residual operational risk: selected detail adds one serialized read per ten
seconds plus reconnect/resync reads. This is intentionally eventual inspection,
not a canonical Event stream, and does not guarantee freshness while requests
fail. No load test or full service-tree pytest run was performed.
