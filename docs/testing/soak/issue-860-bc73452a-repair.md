# Issue #860: bounded CI repair bc73452a

## Frozen scope

- Sole item: issue #860, branch `auto-860`, starting HEAD
  `c5baae54034e878cd63eb073b8fcf7e377aaa3a0`; supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean; no salvage diff required.
- Inspect the supplied dispatch snapshot, cited prior result/check log, repository
  instructions, relevant ADRs, existing soak harness/profile/tests, and the exact
  vulture gate. No GitHub mutations or unrelated repairs.
- Candidate edits: this report, `quality/vulture-baseline.json` only if the actual
  scan requires reviewed retained identities, and issue-860 code/tests only if
  fresh evidence identifies a focused repair. No grant edits.
- No `check-*.log` files existed in this job directory at initial inspection.
  Treat earlier verification as claims, not fresh acceptance evidence.
- Assumption: this is a writer CI-repair round, not permission to invent an RC
  identity, weaken promotion checks, or implement #842's distributed limiter.

## Progress

Fresh exact vulture scan passed: 1323 reviewed identities / 1323 findings,
zero unclassified or never-allowlist findings. No ledger edit is justified.
The cited prior `check-3.log` failed on a 21-versus-24 DDL count. Current test
already includes the three validation-audit columns; fresh focused validation
passed: `uv sync --locked --extra dev`, then `uv run pytest
packages/maistro-core/tests/persistence/test_pg_learnings.py
tests/test_soak_promotion_gates.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
**103 passed, 6 skipped**. The skips are not live-database acceptance evidence.
No source or test repair is supported by these results.

## Architecture and fresh acceptance audit

Read `docs/README.md` and accepted ADR-085, ADR-081626-f383,
ADR-082126-f69c and ADR-082526-b36a. The canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model remains authoritative;
schedules admit Runs, the canonical store owns fences, and lease reclamation
requires evidence of expired liveness rather than restart-implies-death.
No competing authority was introduced. #842's documented process-local limiter
is not reinterpreted as satisfying #860's stronger replica non-bypass criterion.

Production reachability was checked: `main.py:648` installs
`RateLimitMiddleware`; `api/rate_limit.py:95` constructs its in-memory limiter.
The executed test at `tests/test_soak_promotion_gates.py:439` observes
`[200, 200, 429]` on each of two instances with the same authenticated principal
or pre-auth client. This falsifies a shared allowance, not authentication itself.

| Acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC users/Workspaces, request mix, Graph fan-out, schedules, tools/models, Design/Canvas and workers | **UNVERIFIED.** Profile documents gaps; driver `run_soak.py:1373` uses one key and `:1381` has only health/task/receipt/metrics traffic. No selected RC workload was supplied. |
| At least two application replicas | **UNVERIFIED for RC.** `deploy/docker-compose.prod.yml:27,79` defines two replicas, but configuration is not observed deployment. ASGI middleware tests do not constitute a production soak. |
| Sustained saturation, queue growth, lease reclaim, retries, leak and restart observations | **UNVERIFIED.** Historical round43 evidence reevaluated below lasts 420.09 seconds, not the 14400-second profile minimum. No new soak executed. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | **UNVERIFIED.** Driver `:1496` runs admission probes after sustain; admission receipts and a single occurrence race cannot account for physical effects during sustained work. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED overall; contrary allowance evidence reproduced** by the production-middleware test above. Local 429 enforcement is not replica-independent enforcement. |
| PostgreSQL sessions/latency/locks, application loop, worker/process/RSS/fd/queue/error telemetry with thresholds | **UNVERIFIED.** Driver `:1410` measures its own loop, not the application's. No full exact-RC telemetry series captured. |
| Active-work kill/restart, drain/fencing/recovery without loss/duplication | **UNVERIFIED.** Driver `:1427` signals/restarts a process; readiness rejoin and terminal Run counts alone cannot prove physical-effect correctness. |
| Long soak of exact RC/config, repeated after changes | **UNVERIFIED.** Executed evaluator rejects duration and artifact identity; `preflight_artifact_check` at `:730` rejects host-process equivalence. |
| Load findings filed/reclassified to earliest milestone invariant | **UNVERIFIED.** Local recording is not a complete disposition audit; no GitHub mutations performed. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC.** Historical host evidence is not current immutable-image evidence. This report records validation only. |

## Remaining validation results

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files already formatted.
- `uv run python -` imported the actual `scripts/soak/run_soak.py` module and
  evaluated `docs/testing/soak/evidence/m3a-round43-shakedown.json` with
  `failed_promotion_checks`: observed 420.09 seconds, minimum 14400;
  failures `sustain_duration`, `exact_rc_artifact`. Assertions confirmed both
  failures and that the current artifact check returns false. This reevaluates
  retained evidence; it does not claim a new load run.

## Disposition

**BLOCKED.** The reported CI failure is stale and the vulture gate has no debt
to amend. Inventing ledger edits would not repair an observed failure. No tests
were added or changed, so no inventory note is required. Only this report was
changed; all inherited source and evidence remain preserved.

Next required input/work: select the immutable RC and runtime configuration,
complete its representative workload definition, resolve the replica-budget
acceptance mismatch with the security owner, and run a production-topology soak
with application telemetry and physical-effect/fencing accounting. A longer run
of the current host preflight cannot satisfy the exact-artifact gate. Repeating
this same CI repair cannot supply those missing release inputs.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and representative production soak"}`.
Local commit contains this bounded validation report only; no integration approval.
