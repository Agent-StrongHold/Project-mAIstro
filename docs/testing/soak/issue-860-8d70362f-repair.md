# Issue #860 — bounded repair checkpoint (8d70362f)

## Frozen scope and inputs

- Issue #860 only, assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head `7e7b9d362201e3e5e03a0a13ab9e091e968cb3c0`; supplied develop base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`. Initial tree clean.
- Input: job `8d70362f53da4b55b8d0b7c3d0063f5b/dispatch-context.json`, prior result
  `292cbcafdfa048a48181f0ab54003099/result.json`, and supplied failure
  `98a11313167b41a98a420abfda80c292/check-3.log`. No current-job check logs
  existed in the initial directory snapshot. No GitHub requests or mutations.
- Review surfaces fixed to the schema-fence implementation/test, soak harness,
  promotion tests/profile, production rate middleware, relevant ADRs and
  exact vulture gate/ledger. Edit only reproduced defects on those surfaces,
  required test inventory notes, and this checkpoint.
- Ambiguity: no immutable RC artifact/configuration is designated by the
  assignment. Treat this as a writer CI-repair lane, not permission to select
  or certify a substitute deployment. RC designation remains UNRESOLVED.

## Fresh results

- Exact requested gate passed:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
  1323 findings / 1323 reviewed identities; unclassified 0; never_allowlist 0.
  Gate-selected base `4aa68edc0b6b`. No evidenced ledger amendment is needed.

- Focused regression command passed: 103 passed, 6 skipped in 2.55s:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`.
  The supplied DDL failure did not reproduce. PostgreSQL skips are not live DB evidence.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed
  (3270 files already formatted).

## Evidence reviewed

The schema test already independently expects the three validation audit columns
missing from the old failure log (`test_pg_learnings.py:171–175`). Production
holds its advisory lock inside the transaction before DDL
(`pg_learnings.py:215–216`). No code/test change is justified by the stale log.

The executed production-middleware regression
`tests/test_soak_promotion_gates.py:439` shows the same identity receiving
200,200,429 independently on each replica instance (authenticated and
unauthenticated cases). `api/rate_limit.py:93` constructs an in-memory limiter.
This reproduces independent allowances, not a cluster-wide non-bypass guarantee.

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and canonical principal
resolution. Reconciliation: b36a extends f383's original deferred-reclaim
boundary with TTL, fenced renewal, heartbeat and reclamation; #860 must observe
that existing authority under load, not create a second scheduler/reclaimer.
No live reclaim or production soak has been run in this repair.

Additional fresh checks passed (exit 0):

- `uv run python scripts/check-deployment-claims.py` (component existence only).
- `uv run python scripts/check-merge-markers.py`.
- `uv run python scripts/check-backlog-consistency.py` (168 items).
- `git diff --check`.

Production reachability confirmed: `maistro_server/main.py:648` installs
`RateLimitMiddleware`. The snapshot's latest issue comments and draft PR #1672
body provide no RC designation or new completed-soak evidence.

## Acceptance matrix

| #860 acceptance criterion | Executed evidence / remaining requirement |
| --- | --- |
| Representative RC profile covering users/Workspaces, request mix, fan-out, schedules, queue, tool/model calls, Design/Canvas and workers | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:151–170` explicitly lists missing users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker traffic. |
| At least two application replicas in supported deployment | UNVERIFIED for RC. Executed tests use two production middleware instances, not two deployed RC replicas. |
| Sustained load observing saturation, queue growth, reclaim, retries, memory/leaks, shutdown/restart | UNVERIFIED. Focused regressions are not long-running load; six skipped DB tests supply no PostgreSQL observation. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal operations | UNVERIFIED. Profile lines 193–203 state that the occurrence probe cancels its queued Run without execution; admission deduplication is not physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT PROVEN. Fresh production-middleware test at `tests/test_soak_promotion_gates.py:439` reproduces independent allowances for the same identity; per-process enforcement is not the stronger #860 guarantee. Backpressure tests pass but do not establish distributed security. |
| Complete PostgreSQL, event-loop, worker/process, RSS, descriptor, queue and error telemetry with thresholds | UNVERIFIED. No fresh RC telemetry. Profile lines 151–170 acknowledge missing application-loop/worker and long-window observations. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. No deployed active-work fault injection executed. Exit/rejoin and terminal counts alone cannot prove physical recovery. |
| Long-running exact RC artifact/configuration soak and rerun after runtime changes | BLOCKED / UNVERIFIED. No immutable RC/config designation. `scripts/soak/run_soak.py:730` rejects host-process preflight certification; executed four-hour-preflight CLI regressions preserve this fail-closed behavior. |
| Findings filed/reclassified to earliest broken invariant before promotion | UNVERIFIED externally. Local findings recorded here; no GitHub mutation permitted or performed. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for RC. This report binds source validation to the starting head, not to a promoted deployed artifact. |

## Disposition and handoff

**BLOCKED**, not merge-ready. This round found no reproduced CI defect or
unbanked vulture identity to repair. Altering a clean ledger or weakening
artifact/soak gates would not address actual evidence. No code, tests, gates,
grants or ledger changed; only this report was added. Test inventory delta is
zero, so no inventory note is required. All inherited work was preserved.
The broad inherited branch diff is not certified by these focused checks.

Next required work: designate the immutable RC and normalized runtime config;
complete representative workloads and missing telemetry; reconcile independent
replica rate allowances through the canonical security path; execute the actual
long-running exact-artifact soak with active-work recovery and physical-work
observation. Do not repeat this stale CI failure as a substitute for those
prerequisites. No merge conflict exists in the assigned tree; no develop sync,
push, PR creation, issue closure or other remote mutation was performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
This report is committed locally as the writer checkpoint, not integration approval.
