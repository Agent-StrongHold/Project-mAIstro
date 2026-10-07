# #860 — evidence-backed CI repair disposition (ae0b976b)

## Scope and result

**BLOCKED for issue acceptance. The dispatched CI failure is already repaired.**

Frozen item: issue #860 only, worktree `auto-860`, starting HEAD
`875e50d7e5a162fe456d9529647dea9b2ca287d9`, supplied develop base
`f23f49012a31dd00b88e7797a46f15c0e610ec9f`. Both resolve locally; the worktree
started clean. Read the supplied dispatch snapshot, repository instructions,
prior result and prior `98a11313.../check-3.log`. The current job directory had
no driver `check-*.log` files at initial inspection. Fresh checks below replace
prior verification claims; no remote lists were refreshed or GitHub mutated.

The old failure expected 21 DDL statements but observed 24. At the assigned
HEAD, `packages/maistro-core/tests/persistence/test_pg_learnings.py:173-177`
already independently enumerates the three Gauntlet audit columns. The test
passes against production `PgLearningStore.ensure_schema()`; the container
calls that method at `packages/maistro-core/src/maistro/container.py:3090`.
No assertion was relaxed or generated from production constants.

The requested vulture scan also passes: **1,332 reviewed identities / 1,332
findings**, zero unclassified and zero never-allowlist findings. Its arguments
match `.github/workflows/vulture-ratchet.yml:82-85`; the scanner reports its
trusted base as `1df433bf5ece`. There is no unbanked identity to review or amend.
A ledger edit or speculative source change would not repair actual evidence.

Only this handoff changes. No production code, tests, inventory, ledger,
authorizations, gates, runtime configuration or historical evidence changed.
No new tests means no inventory-delta note is needed.

## Architecture and production reachability

Read the documentation authority hierarchy, accepted execution-lease ADR
`ADR-081626-f383`, graph protocol ADR-062, production schema/rate middleware,
adjacent tests, soak profile and promotion evaluator. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model. The lease ADR establishes
stale-writer fencing, not a blanket exactly-once physical-work guarantee;
receipt deduplication cannot substitute for active-work recovery evidence.
No competing scheduler, store, authority or authorization path was introduced.

The attempted path `docs/adr/ADR-081-production-deployment-profile.md` was not
found; skipped, not treated as a verified ADR or retried under a guessed name.
The actual topology limitation is independently explicit in the inspected
profile and executable artifact gate.

- `maistro_server/main.py:648` installs the exercised `RateLimitMiddleware`.
  `api/rate_limit.py:69-78` constructs its limiter per instance; lines 25-30
  explicitly document N times the local allowance across N replicas.
- Executed `test_replica_selection_has_an_independent_production_allowance`
  (`tests/test_soak_promotion_gates.py:439-488`) exhausts the same identity on
  replica one, then observes two more accepted requests on replica two.
  Authenticated and unauthenticated cases both pass. This is a real middleware
  seam with ASGI transports, not a deployed multi-replica soak or proof of an
  aggregate budget. Do not reconcile #860's non-bypass requirement by silently
  redefining it to mean only local enforcement.
- Task-backpressure tests traverse the real router, queue and canonical Run
  spine, deliberately without a worker. They establish retryable admission
  behavior, not physical execution uniqueness.
- `scripts/soak/run_soak.py:730-741` always rejects its host-process topology as
  exact-RC certification. Its generated evidence wires that check at line 1552
  and the duration check at lines 1599-1602. A longer host run cannot close the
  artifact requirement.

## Executed validation

Logs are in job directory
`/home/dev/maistro/jobs/ae0b976be7ba4a12a484ed1cdce092f0/`.
All validation used 600- or 1,200-second tool timeouts.

| Command | Fresh result / log |
| --- | --- |
| `uv sync --locked --extra dev` | PASS; `worker-sync.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 PostgreSQL-dependent skips; `worker-schema.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, exact 1,332 identities; `worker-vulture.log` |
| `uv run ruff check .` | PASS; `worker-ruff.log` |
| `uv run ruff format --check .` | PASS, 3,105 files; `worker-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 104 passed; `worker-acceptance-tests.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 28,182 unique identities, zero duplicate evidence; `worker-inventory.log` |
| `uv run python -` importing the current driver and evaluating frozen round-30 JSON | Assertions PASS: rejected by `sustain_duration` and `exact_rc_artifact`; `worker-evidence.log` |

The evidence evaluation observed **420.08 seconds versus 14,400 required**.
It is a fresh evaluation of historical evidence, not a newly executed soak.
No live PostgreSQL concurrency test, live replica deployment, destructive
restart or long-running load was performed this round.

## Acceptance matrix

| Issue criterion | Disposition and executed evidence |
| --- | --- |
| Representative users/Workspaces, request mix, Graph fan-out, schedules, queue, tools/models, Design/Canvas and workers | **UNVERIFIED.** Profile exists, but `m3a-load-profile.md:153-172` explicitly lists missing classes. No selected-RC workload justified those omissions. |
| At least two production application replicas | **UNVERIFIED live.** Two middleware instances were exercised, not the selected production deployment. |
| Sustained saturation, queue growth, reclaim, retries, memory/descriptor/process leaks and shutdown/restart | **UNVERIFIED.** Sampler regressions pass; the evaluated historical duration fails the minimum. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED.** Admission tests pass but do not execute physical workers. Profile lines 195-204 distinguish a cancelled schedule-probe Run from sustained reconciliation. |
| Rate/security/degraded concurrency behavior, without replica-selection bypass | **NOT PROVEN.** Executed real-middleware tests demonstrate independent allowances on replica selection. Broader deployed security/degraded behavior is **UNVERIFIED**. |
| Complete PostgreSQL/query/lock, application-loop, worker/process/RSS/FD, queue/error/timeout telemetry and thresholds | **UNVERIFIED at promotion grade.** No new production series; driver-loop measurements are not application-loop measurements. |
| Active-work kill/restart, drain/fencing/recovery without silent loss/duplication | **UNVERIFIED.** No active-Attempt restart was executed. Boot cleanup tests alone do not establish the criterion. |
| Long-running exact RC/configuration soak, repeated after changes | **NOT MET by evaluated evidence.** 420.08 < 14,400 seconds and artifact check fails. |
| Findings filed/reclassified to earliest broken milestone before promotion | **UNVERIFIED for completeness.** Local evidence retained; no GitHub mutations permitted or performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for a promotion RC.** Existing historical JSON is not exact-RC certification. |

## Handoff

Do not redispatch the stale schema failure or already-passing vulture ledger as
an actionable repair. The next work requires an immutable RC/configuration,
representative production workload and telemetry/physical-work oracles,
resolution of the replica-selection budget requirement, then an exact-artifact
soak lasting at least four hours. Clean deterministic checks do not waive those
prerequisites. No merge conflict exists; conditional develop-conflict repair
was not applicable.

Issue progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: production acceptance prerequisites}. The bounded CI investigation is
complete; the issue remains blocked, without integration approval.
