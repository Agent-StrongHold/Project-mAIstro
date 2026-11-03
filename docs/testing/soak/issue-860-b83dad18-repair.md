# Issue #860 repair — b83dad18

## Frozen scope

- Issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `2309d295224236980a9c1ea8f0a2aea73aa1c1b4` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean; no salvage patch needed.
- Process the supplied schema-fence failure, exact vulture CI repair, and acceptance evidence. No linked PR processing or GitHub mutations.
- Candidate edit scope: this report; `quality/vulture-baseline.json` only if the executed scanner identifies reviewed retained identities; `packages/maistro-core/tests/persistence/test_pg_learnings.py` and corresponding inventory note only if the reported failure reproduces. Read-only acceptance surfaces: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`, `docs/testing/soak/m3a-soak-evidence.md`, retained soak evidence and production middleware/schema wiring.
- No `check-*.log` files present in this job directory at initial snapshot. Supplied previous `98a113.../check-3.log` reports 24 DDL calls vs 21 expected; prior result claims resolved, not yet trusted.
- Ambiguity: the assignment requests both full acceptance and a CI repair. Proceed with focused fresh validation; do not interpret unit/preflight success as production RC promotion evidence.

## Results

Exact requested vulture scan passed (exit 0): 1323 reviewed identities and 1323 findings, zero unclassified or never-allowlist findings. Output: `/tmp/860-b83dad18-vulture.log`. No evidenced ledger amendment is needed; no identities will be guessed or added.

`uv sync --locked --extra dev` passed. Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. The reported schema-fence failure does not reproduce. `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **66 passed**. `uv run ruff check .` and `uv run ruff format --check .` both passed (3270 files formatted). No source/test repair is justified by these results.

`uv run python -` imported the real soak driver's evaluator and evaluated retained `docs/testing/soak/evidence/m3a-round43-shakedown.json`: observed sustain **420.09 seconds**, minimum **14400 seconds**, failed checks **sustain_duration, exact_rc_artifact**. Assertions verified both failures and that the current `preflight_artifact_check()` is false. This is fresh evaluation of historical evidence, not a new soak.

`uv run python scripts/check-doc-links.py` passed (2660 Markdown files, zero broken links). `git diff --check` passed.

## Architecture and acceptance

Read repository instructions, the documentation authority map, accepted ADR-085, ADR-081626-f383, ADR-082126-f69c and ADR-082526-b36a; inspected the profile, historical evidence pack, production limiter wiring, current schema contract and soak driver/tests. The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model remains unchanged. Schedule admissions must produce canonical Runs, and physical Attempt recovery must obey renewable leases and fencing. A receipt count or successful process restart cannot substitute for physical-work accounting. ADR-085 requires principal keying; the process-local #842 implementation does not prove #860's stronger replica-selection non-bypass requirement. No alternative scheduler, authorization path or execution authority is introduced to bridge that gap.

Acceptance criteria below are transcribed from the supplied dispatch's issue body, not inferred from previous verification claims.

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile: concurrent users/Workspaces, Graph fan-out, schedules, tasks, tools/models, Canvas and background work | **UNVERIFIED.** `scripts/soak/run_soak.py:1373` uses one credential; its mix at 1381 contains health/task/receipt/metrics traffic. The profile's remaining-gaps section explicitly excludes successful model/tool work, fan-out and sustained Goal reconciliation. No selected RC configuration justifies those exclusions. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Passing tests exercise two production-middleware instances; they are not immutable deployed RC replicas. Historical preflight logs do not establish current artifact behavior. |
| Sustained saturation, queue growth, expiry/reclaim, backoff, resource leaks and restart | **UNVERIFIED.** Fresh evaluator rejects the retained 420.09-second sustain. Passing sampler/accounting tests are not observations of long-running production load. |
| Schedule/task/Run/Attempt/Goal operations do not duplicate physical work across replicas | **UNVERIFIED.** The driver evaluates task receipt identities and schedule admission separately from the sustained phase (`run_soak.py:1496`); those do not prove physical effects or Goal desired-state reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Contrary allowance evidence reproduced.** `tests/test_soak_promotion_gates.py:439` passes for both authenticated and pre-auth identities: each production middleware instance independently allows `[200, 200, 429]`. The implementation constructs `InMemoryRateLimiter` at `packages/maistro-server/src/maistro_server/api/rate_limit.py:95`; production installs that middleware at `main.py:648`. Full deployed security/degraded behavior remains **UNVERIFIED**. |
| PostgreSQL/app-loop/worker/RSS/fd/queue/error telemetry with explicit thresholds | **UNVERIFIED.** `run_soak.py:1410` samples the driver's loop, not application loop latency. No complete fresh production series with all requested thresholds exists in this validation. |
| Kill/restart during active work, proving drain/fencing/recovery | **UNVERIFIED.** Driver kill/rejoin starts at `run_soak.py:1427`; post-settle terminal Run counts do not establish physical-work loss/duplication accounting. No new active-work deployment run was performed. |
| Long soak of exact RC artifact/configuration; rerun after changes | **UNVERIFIED.** Fresh evaluation fails duration and artifact gates. `run_soak.py:730` deliberately rejects its host-process topology even if run for four hours. |
| Load findings filed/reclassified before promotion | **UNVERIFIED.** Historical evidence has local finding dispositions; no fresh acceptance proof of complete filing/reclassification. No GitHub mutations were performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Retained host-preflight evidence and this report cannot establish promoted image/configuration identity. |

## Disposition and handoff

**BLOCKED.** The supplied schema failure is stale at this head and the exact vulture scan is clean. Neither warrants speculative source changes or ledger additions. No merge conflict is present, so the conditional develop-sync repair does not apply. Only this report changes; no tests were added and no inventory delta is needed. Inherited work is preserved, not independently approved by these scoped checks.

To continue: supply/select the immutable RC image and deployment configuration; implement/run a representative production-path soak with full telemetry and physical-work accounting; resolve the replica-budget acceptance mismatch through the existing security authority; then run the long soak and publish hash-bound evidence. Extending this host-preflight run or repeating the stale CI failure cannot satisfy those prerequisites.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC deployment/profile and production soak acceptance evidence"}`. Focused validation is complete for local handoff only; issue acceptance is not complete.
