# Issue #860 repair checkpoint — 105a0787

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `1837e30bc1aa3eb9d35c919f21c8d726998d92ff`, supplied base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Worktree initially clean. No salvage required. No remote mutations.
- Inspect existing soak runner/profile/tests and relevant architecture; reproduce
  exact vulture CI scan before deciding whether ledger repair is warranted.
- Potential edits restricted to evidence-backed soak repairs, their tests/inventory
  note, reviewed vulture identities (explicit lane exception), and this report.
- Current job directory contains no `check-*.log`; inspect supplied prior failure.
- Ambiguity: lane requests CI repair but prior result reports missing exact-RC
  evidence. Treat these as separate checks; passing lint cannot prove a soak.

## Progress

- Exact requested vulture scan passed: 1,322 reviewed identities/findings,
  zero unclassified and zero never-allowlist findings. No ledger edit warranted.
- Supplied historical `check-3.log` is a learning-schema test failure (24 versus
  21 DDL statements), not a vulture failure. Fresh execution of
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. No speculative schema repair warranted.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed
  (3,301 files).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: 73 tests, including replica-selection allowance and live child-process
  resource sampling. These are targeted regressions, not deployed soak evidence.
- `uv run python scripts/check-suite-inventory.py` passed: 17 suites,
  31,327 unique identities, no duplicates. No tests changed or added.
- Profile review confirms this is a host-process preflight, not an RC Compose
  runner; one identity and absent successful model calls do not meet the full
  representative workload. Prior claims remain historical evidence, not proof
  of production acceptance.
- `uv run pytest packages/maistro-server/tests -x -q` passed: 558 passed,
  8 skipped, 25 warnings. Three warnings were unhandled aiosqlite worker-thread
  exceptions (`Event loop is closed`) reported during
  `test_task_submission_at_capacity_returns_429_without_retained_claim`;
  22 were Starlette deprecations. These warnings remain unresolved; a passing
  suite is not evidence of leak-free production lifecycle.
- Executed the current evaluator with `uv run python` against the frozen
  historical `evidence/m3a-round30-shakedown.json`: failed checks are
  `sustain_duration` and `exact_rc_artifact`; 420.08 seconds observed versus
  14,400 required. Also asserted `preflight_artifact_check()['ok'] is False`.
  This re-evaluates old evidence; no new production load was run.
- One inspection path (`maistro_server/middleware/rate_limit.py`) was not found;
  skipped it and read the actual `api/rate_limit.py` imported by the test.

## Architecture and acceptance

Read accepted ADR-081426-1f7c and ADR-081626-f383. Physical execution identity
is Attempt; canonical Run persistence owns fencing. The latter ADR explicitly
leaves lease-expiry takeover undefined. Therefore schedule admission uniqueness
and process rejoin cannot substitute for physical Attempt recovery evidence.
No new scheduler, store, authorization path, or reclaim authority was introduced.

| # | Acceptance criterion | Evidence and remaining gap |
|---|---|---|
| 1 | Representative RC workload | UNVERIFIED. `m3a-load-profile.md:165` documents missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal workers. No immutable RC/configuration was designated by this assignment. |
| 2 | Two production replicas | UNVERIFIED. Executed tests use two real middleware instances, not production Compose replicas. `run_soak.py:744` identifies host-process preflight. |
| 3 | Sustained saturation/retry/leak observations | UNVERIFIED. Executed evaluator rejects sampled 420.08-second historical evidence against the 14,400-second minimum. No new sustained run. |
| 4 | No duplicate physical work | UNVERIFIED. Admission regressions pass; `run_soak.py:1091` cancels the schedule probe Run without executing it. This cannot establish physical Attempt uniqueness or Goal recovery. |
| 5 | Replica-independent security/degradation | NOT PROVEN. Executed `test_replica_selection_has_an_independent_production_allowance` for both identity types: each replica independently returns 200,200,429. Switching replicas increases available budget, consistent with `api/rate_limit.py:32` but insufficient for a shared-budget interpretation of this criterion. Full deployed concurrent security remains UNVERIFIED. |
| 6 | Complete metrics with thresholds | UNVERIFIED. Live sampler regression passes for child RSS/descriptors. Profile explicitly measures driver loop lag, not application loop lag, and no complete exact-RC series was captured. |
| 7 | Active-work kill/restart fencing/recovery | UNVERIFIED. No active production Attempt kill/restart performed; process rejoin alone does not prove this. |
| 8 | Long soak of exact RC/config | UNVERIFIED. Current evaluator rejects historical duration and artifact checks. Extending the host-process runner cannot satisfy the exact-artifact gate. |
| 9 | Findings filed/reclassified | UNVERIFIED at promotion grade. Existing human report has local findings, including F11/F12. No external filing/reclassification verified or performed; GitHub mutations prohibited. |
| 10 | Hash-bound machine/human RC evidence | UNVERIFIED for the promoted artifact. Historical JSON/human reports exist, but no new immutable RC image/configuration evidence was produced. |

## Disposition and handoff

**BLOCKED.** Only this report changed. No production-code, test, inventory,
ledger, grant, or gate edits were justified by the reproduced checks. No new
tests means no inventory delta is required. No integration approval or issue
closure implied.

Next: designate the immutable RC images/configuration and production topology;
complete its representative workload and application metrics; reconcile the
replica-selection budget requirement with documented process-local enforcement;
then execute and publish a >=4-hour exact-RC soak with physical Attempt
restart/fencing evidence after runtime configuration is frozen. Do not substitute
another passing unit/ledger run for these missing prerequisites. Investigate
SQLite teardown warnings separately before drawing leak-free conclusions.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC prerequisites and production soak"}`.
All validation commands above exited zero; unverified acceptance remains blocked.

