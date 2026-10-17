# #860 focused repair validation — 4030f4f4

## Scope and disposition

Assigned worktree `auto-860`, starting HEAD
`048501a6794a53283cb4ab02e02c876f3746203e`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial tree clean. Processed
only #860 and its supplied failure; no remote mutations or merge performed.
This is a writer handoff, **BLOCKED**, not promotion approval.

The supplied historical `98a11313167b41a98a420abfda80c292/check-3.log`
expects 21 schema statements against 24. Fresh execution does not reproduce
it: `test_pg_learnings.py:173` already includes the three Gauntlet audit
columns. Production `pg_learnings.py:216` fences all upgrades in the same
transaction. No production or test repair is warranted by that stale log.
The current job directory had no driver `check-*.log` files at initial inspection.

The explicitly requested exact vulture scan also passes. No unbanked or stale
identities were reported; changing `quality/vulture-baseline.json` would not
repair an observed failure. Only this report changes; no test inventory delta.

## Commands executed

- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1323 reviewed identities / 1323 findings, zero unclassified and
  never-allowlist findings. Matches both vulture CI invocations.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Skips require a migrated PostgreSQL test database.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run python scripts/check-doc-links.py`: PASS, 2656 Markdown files,
  zero broken relative links. `git diff --check`: PASS.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed**. This includes real production middleware instances and
  process-group sampling, plus canonical task-route backpressure tests.
- `uv run python -` importing `scripts/soak/run_soak.py`, loading retained
  `evidence/m3a-round43-shakedown.json`, and asserting rejection by
  `failed_promotion_checks`: PASS. Rejected checks are `sustain_duration`
  (420.09 seconds versus 14400 minimum) and `exact_rc_artifact`.
  Also asserted `preflight_artifact_check()['ok'] is False`.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: available PostgreSQL
  containers are not proof of an RC deployment. Did not point integration
  fixtures at these shared databases: the fixture truncates application tables.

Local command logs and evaluator JSON are under job directory
`/home/dev/maistro/jobs/4030f4f42e46436f82a111d75c86fc9c/`.

## Architecture and reachable behavior

Read repository guidance and accepted ADR-085, ADR-081626-f383,
ADR-082526-b36a and ADR-082126-f69c. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: schedules produce canonical
Runs; Attempt leases and renewal/reclaim belong to the canonical execution
spine. The later reclaim ADR extends the earlier fencing contract, so absent
soak evidence must not be described as an absent reclaim design.

ADR-085 requires principal-keyed limits. The current implementation documents
per-process budgets, not a shared budget. `maistro_server/main.py:648` installs
`RateLimitMiddleware`; `api/rate_limit.py:93` creates its independent in-memory
limiter. Fresh execution of `tests/test_soak_promotion_gates.py:439` confirms
that the same identity gets `[200, 200, 429]` on replica one and then again on
replica two. This is local enforcement evidence, not fulfillment of #860's
stronger replica-selection non-bypass criterion. No new authorization path or
policy waiver is introduced.

## All ten acceptance criteria

| Criterion | Executed evidence / gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Inspected `m3a-load-profile.md` and `run_soak.py:1373`: one credential and five request classes; no representative concurrent Workspace population, Graph fan-out, successful model/tool, Canvas or Goal/background work. |
| At least two deployed RC replicas | **UNVERIFIED.** Two middleware instances were exercised, not immutable deployed RC application replicas. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | **UNVERIFIED.** Evaluator rejects the retained 420.09-second run. Passing sampler tests cannot establish sustained load behavior. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | **UNVERIFIED.** Receipt/admission checks do not prove physical effects; the profile's schedule probe cancels its queued Run without execution. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Contrary middleware evidence reproduced** as described above. Full RC concurrency/security/degraded behavior remains **UNVERIFIED**. |
| Full telemetry with pass/fail thresholds | **UNVERIFIED under RC load.** Sampler tests pass, but `run_soak.py:1410` measures driver loop lag, not application event-loop latency; no complete fresh production series captured. |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED.** Reviewed signal/rejoin logic at `run_soak.py:1427`; no new active-work deployment run or physical-effect accounting executed. |
| Long exact-RC artifact/configuration soak | **UNVERIFIED / BLOCKED.** Fresh evaluator rejects duration and artifact. `run_soak.py:730` explicitly refuses host-preflight equivalence; no exact promoted artifact/configuration was validated here. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED.** No external disposition verification or GitHub mutations; historical records are not current closure evidence. |
| Machine/human evidence bound to promotion hashes | **UNVERIFIED for RC.** Retained JSON fails promotion checks. This report and local evaluator output are validation evidence only. |

## Next action

Stop redispatching the historical schema failure as a current code defect.
Select the immutable RC/configuration, resolve the replica-budget acceptance
mismatch through the existing policy authority, and execute a representative
long production-path soak with physical-effect/recovery accounting and complete
telemetry. No speculative code or ledger changes, discarded evidence, gate
weakening, or integration approval in this round.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC acceptance evidence and replica-budget resolution"}`.
