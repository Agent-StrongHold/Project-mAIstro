# Issue #860 repair checkpoint (eb06b9bb)

## Frozen scope

- Issue #860 only; branch `auto-860`, clean starting HEAD
  `07518ed6cd8364f0030c28608a49fdb8a88b59ff`; supplied base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62` resolves locally.
- Inputs: supplied dispatch-context.json, prior ca230525 result, cited
  98a11313/check-3.log. No GitHub refresh or mutations.
- Inspection/validation: repository instructions, relevant ADRs, existing soak
  runner/promotion tests, production middleware, exact vulture CI gate.
- Candidate edits: this report and only identities actually reported by the
  vulture gate (reviewed source/adjacent tests and ledger if necessary).
- No current-job check-*.log files were present at initial directory inspection.
- Prior BLOCKED claims are inputs, not verified results. No integration approval
  follows from local static or unit checks.

## Progress

Initial worktree clean. No salvage needed.

Fresh exact vulture scan passed: 1322 findings / 1322 reviewed identities,
zero unclassified or never-allowlist findings. No ledger repair is justified.
The supplied historical check-3.log is a schema-fence expectation failure
(24 statements vs 21), not vulture debt. Fresh execution of
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped. The cited failure does not reproduce.
Both commands used a 1200-second timeout.

Additional fresh commands (1200-second timeout):

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  99 passed.

Total: 136 passed, 6 skipped. Database-dependent skips are not acceptance
proof. No test additions or modifications; no inventory delta required.

## Architecture reconciliation and observed behavior

Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve Goal -> Graph -> Run -> NodeRun ->
Attempt; no alternate execution, authorization or persistence authority added.

**Correction to prior ca230525 handoff:** its statement that the lease ADR does
not yet authorize expiry takeover omits accepted ADR-082526-b36a. That later
contract defines fenced renewal, expiry reclamation and canonical recovery.
`packages/maistro-core/src/maistro/container.py:1260` calls
`run_store.reclaim_expired_attempts`. Thus soak reclamation remains UNVERIFIED,
not prohibited by architecture. This round did not execute recovery under load.

The production app registers `RateLimitMiddleware` in
`packages/maistro-server/src/maistro_server/main.py:648`. The constructor at
`api/rate_limit.py:93` allocates an in-memory limiter per instance; the module
explicitly documents N-times aggregate budgets. Executed regression
`tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` separately
on each of two middleware instances for the same identity (authenticated and
unauthenticated variants). This falsifies shared-budget enforcement at that
seam, not the whole deployed ingress/security posture. It cannot satisfy the
issue's stronger replica-selection requirement merely by renaming the budget.

The production-router receipt probe at `tests/test_soak_promotion_gates.py:569`
passes while observing a peer-local 404. Shared admission identity is not
physical-work uniqueness. These ASGI probes are not deployed replicas.

`scripts/soak/run_soak.py:744` intentionally rejects artifact equivalence for
its host-process preflight. The executed CLI tests reject missing/null/preflight
artifact records even with a simulated four-hour duration. Keeping that gate
closed is correct; another preflight smoke would not establish RC evidence.

## Acceptance disposition (all ten issue criteria)

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED: profile at `docs/testing/soak/m3a-load-profile.md:165` still excludes concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and background/Goal activity pending RC applicability. |
| At least two deployed application replicas | UNVERIFIED: two ASGI instances are not a deployed production topology; none deployed this round. |
| Sustained saturation, queue growth, reclaim, retries, leaks | UNVERIFIED: short regression checks do not measure sustained behavior. Reclaim is supported by the later ADR but untested under soak here. |
| No duplicate physical work across replicas | UNVERIFIED: observed admission/receipt identities do not establish physical Attempt or Goal work uniqueness. |
| Replica-selection-resistant rate/security/degraded behavior | NOT SATISFIED at the tested middleware seam: independent allowances reproduced. Deployed ingress/security/degradation remains UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED: no fresh production PostgreSQL contention, application-loop, queue, worker, RSS/FD and error/timeout series. Driver-loop lag cannot substitute for application-loop lag. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: no replica killed during real production work this round. |
| Long exact-RC soak | UNVERIFIED: existing runner is explicitly preflight-only; no selected immutable RC image/config supplied by this assignment. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness: local rate/receipt correctness prerequisites recorded; no GitHub mutation performed. |
| Published hash-bound machine/human production evidence | UNVERIFIED: this source-bound report is not an image/package/config-hashed production soak bundle. |

## Handoff

BLOCKED. Only this report changed. No source, test, ledger, grant, gate or
execution authority changed. There was no develop-sync conflict to resolve.
The exact-debt gate is synchronized, and the historical failure already passes;
amending its ledger or weakening tests would not repair actual evidence.

Next: select an immutable RC deployment and representative workload, resolve
replica-local enforcement/receipt correctness prerequisites through existing
production seams, then execute and retain the long production soak and all
required telemetry/recovery evidence. Do not re-dispatch the historical schema
failure or clean vulture scan as an actionable CI repair without new evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. Writer handoff only, never integration approval.
