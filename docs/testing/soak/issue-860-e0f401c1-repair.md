# #860 repair validation — e0f401c1

## Disposition and frozen scope

**BLOCKED: validation handoff only, not integration approval.** Assigned issue
#860, branch `auto-860`, worktree `/home/dev/Git/wt/auto-860`; clean starting
HEAD `5d7b16f65070b6b0e65617a684e43f59daf93a73` verified locally.
Only this report changes. No test additions (no inventory delta), production
changes, ledger/grant changes, GitHub mutations, or discarded work.

Read repository instructions, documentation authority map, accepted ADRs
081426-1f7c (Attempt/runtime boundary), 081626-f383 (execution fencing),
082526-b36a (renewal/reclaim), and 073126-c4e1 (immutable RC provenance).
The later reclaim ADR extends the earlier fencing boundary; its original
recovery deferral is not an acceptance waiver. ADR-081 is Proposed, not accepted
deployment authority. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`
and all existing execution/security authorities.

Read the supplied dispatch snapshot's issue acceptance and latest primary
comments, supplied previous result, and historical failed check. No current-job
`check-*.log` files were present at entry. No remote list refresh or merge was
performed. The historical schema-test failure is already repaired in the
starting tree; there is no evidence-backed code repair to apply this round.

## Fresh validation

All commands ran in the assigned worktree with 600–1,200-second validation
timeouts. Local logs are in
`/home/dev/maistro/jobs/e0f401c16052413aaeff197cf135fb59/worker-*.log`
(exact Vulture output is in the job tool transcript).

| Command | Executed result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,326 reviewed identities / findings; zero unclassified or never-allowlist. Matches `.github/workflows/quality.yml:1038`. No unbanked identities to amend. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped. Historical `98a11313167b41a98a420abfda80c292/check-3.log` reported 24 versus 21 DDL statements. Current test independently includes the three Gauntlet columns at lines 175–177. Skips do not prove live PostgreSQL behavior. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 100 passed. Includes real production limiter instances, negative probe cases, resource sampler and boot-cleanup checks; not a deployed RC soak. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3,170 files. |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 29,499 unique identities, zero duplicate evidence. |
| `uv run python scripts/check-merge-markers.py` | PASS. |
| `uv run python -` (import current driver, evaluate historical round-30 evidence) | PASS: asserted failures `sustain_duration` and `exact_rc_artifact`; recorded 420.08 seconds versus 14,400 minimum. Also asserted current preflight artifact check is false. See `worker-evidence.log`. No new soak claimed. |

## Acceptance assessment

| Issue criterion | Evidence and remaining prerequisite |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:153–172` identifies missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker traffic. Scope must match the selected RC deployment. |
| At least two application replicas | **UNVERIFIED for RC.** Passing ASGI tests exercise separate middleware instances, not two deployed RC artifacts. |
| Sustained saturation, growth, reclaim, retries and leaks | **UNVERIFIED.** Historical duration is rejected by the current evaluator. No fresh long-running load or saturation observations. |
| No duplicate physical work, including schedules/tasks/Run/Attempt/Goal reconciliation | **UNVERIFIED.** `run_soak.py:1075–1163` probes schedule admission and terminalizes the probe Run, not physical Attempt execution. No sustained Goal desired-state workload. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED as stated.** Executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) observes `[200, 200, 429]` on each replica for the same identity. Production `rate_limit.py:32–37` promises per-process budgets, not a shared cluster budget. Existing seam must reconcile this stronger acceptance; no parallel authorization path added. |
| Complete telemetry and explicit thresholds | **UNVERIFIED complete.** Current driver-loop measurements cannot prove application-loop health; long-window pool/worker/leak observations absent. Profile explicitly records these limits. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED.** Boot cleanup tests and admission evidence do not establish active physical-work recovery or stale-effect rejection. |
| Long soak of exact promoted RC/config | **BLOCKED / UNVERIFIED.** No selected immutable RC/configuration was supplied in the lane assignment. `run_soak.py:730–741` deliberately rejects host preflight as exact-RC evidence. Historical duration fails independently. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED completeness.** Historical findings preserved; no new load run or GitHub mutations. |
| Hash-bound machine/human soak evidence | **UNVERIFIED for candidate.** Historical artifacts retained, not recertified for this HEAD. This report records local validation only. |

## Handoff

Required next input is the selected immutable RC image/package/configuration and
supported deployment contract, followed by a representative production-topology
campaign lasting at least four hours, with complete telemetry and active-work
fault injection. Resolve the per-replica budget acceptance through the existing
security seam. Repeating a clean Vulture scan or extending the host preflight
cannot establish these prerequisites. Do not promote based on unit-test success.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production acceptance execution"}`.
