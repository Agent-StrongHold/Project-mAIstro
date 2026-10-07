# Issue #860 — evidence-based CI repair checkpoint (51affe6d)

## Scope and disposition

**BLOCKED on production acceptance; the assigned CI failures do not reproduce.**
This is a local handoff, not promotion approval or issue closure.

Frozen item: #860 only, branch `auto-860`, assigned worktree
`/home/dev/Git/wt/auto-860`. Starting HEAD verified as
`12e39bceb8371bcec90fa406fe0ac8c76c29f2b2`; supplied develop base
`00382f6575a4d5147dc4327a70b5703c0b68f43b`. Initial tree was clean.
No merge conflict was present. No remote or GitHub mutation was performed.

Evidence snapshot: supplied job `dispatch-context.json` (primary issue acceptance),
prior `1278490322d34ebaaacd2b3cade92c38/result.json`, and the cited
`98a11313167b41a98a420abfda80c292/check-3.log`. No driver `check-*.log`
files were present in this job at start. Current validation logs are
`/home/dev/maistro/jobs/51affe6d5e694b409add662ecc6a9be6/worker-*.log`.
The review was restricted to the issue's soak driver/profile/evidence/tests,
reported schema test failure and adjacent production code, rate middleware,
requested vulture scan, and governing instructions/ADRs.

Ambiguity resolved: a CI-repair dispatch is not evidence that production
acceptance is satisfied. Do not manufacture a scanner fix when the exact scan
passes. Do not designate a host-process shakedown as the promotion RC.

## Reproduced results

All validation used `uv run`, with 1,200-second command timeouts.

| Command | Executed outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,332 findings / 1,332 reviewed identities; zero unclassified or never-allowlist findings. Gate-selected trusted base `1df433bf5ece`, distinct from supplied dispatch base. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,105 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 60 passed, 6 skipped (PostgreSQL-gated); no live PostgreSQL proof claimed |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q` | 81 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 28,182 unique identities, zero duplicate evidence |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |
| `uv run python -` importing current `run_soak.py` and evaluating frozen `m3a-round30-shakedown.json` | Assertions PASS: failed promotion gates exactly `sustain_duration` and `exact_rc_artifact`; observed 420.08 seconds versus required 14,400. Current `preflight_artifact_check()['ok']` is false. Historical evidence evaluation, not a new live soak. |

The old `check-3.log` failure was **24 schema statements versus 21 expected**,
not unbanked vulture debt. Production declares the three audit upgrades at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:118-120`;
the current test independently expects them at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.
The executed schema-fence test passes. Boot reachability is explicit at
`packages/maistro-core/src/maistro/container.py:3090`.

Rate middleware is installed by
`packages/maistro-server/src/maistro_server/main.py:648`.
The executed test at `tests/test_soak_promotion_gates.py:439-488` uses real
middleware on two ASGI instances with the same IP and credential. Both return
`[200, 200, 429]`: exhausting one replica leaves the other allowance available.
This falsifies a shared allowance, but is not a production deployment test.
Task-backpressure tests exercise the real router and canonical admission seam;
they do not start physical workers and cannot prove physical-work uniqueness.

## Architecture reconciliation

Read accepted ADRs 081226-69ee (Graph/Node), 081626-f383 (Attempt fencing),
082526-b36a (lease renewal/reclaim), 082826-08f0 (recovery disposition),
and 085 (principal rate limiting). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. The later recovery disposition
requires refusing recovery of live leased work; process restart or admission
counts cannot substitute for physical-work fencing evidence. No competing
execution, Goal, event, or authorization authority is introduced.

ADR-085 specifies principal identity but does not supply a distributed limiter.
The reachable middleware explicitly documents process-local allowances at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30`.
That implementation is not proof of #860's stronger replica-selection criterion;
no acceptance waiver or silent contract change is made here.

## All issue acceptance criteria

| Criterion | Evidence / remaining gap |
| --- | --- |
| Representative users/Workspaces, request mix, Graph fan-out, schedules, queues, tool/model, Design/Canvas/background work | **UNVERIFIED.** Profile `m3a-load-profile.md:153-172` explicitly identifies missing workloads. No immutable promotion RC/configuration was selected by this dispatch. |
| At least two production application replicas | **UNVERIFIED live this round.** ASGI middleware instances and historical host-process shakedowns do not prove the selected production deployment. |
| Sustained saturation, queue growth, lease reclaim, retries, memory/FD/process leaks and shutdown observations | **UNVERIFIED.** Current evaluator rejects the historical 420.08-second duration; no new long-window production metrics were collected. |
| No duplicate physical schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED.** Driver schedule probe admits a Run rather than executing its physical work; profile `m3a-load-profile.md:195-204` records cancellation of that probe and absent sustained schedule traffic. |
| Security/degraded/rate enforcement cannot be bypassed by replica selection | **Not proven.** Executed production-middleware test demonstrates independent replica allowances. Full concurrent security/degraded acceptance remains **UNVERIFIED**. |
| PostgreSQL connections/query/lock, application-loop, workers/process/RSS/FD/queue/error telemetry with explicit thresholds | **UNVERIFIED at promotion grade.** Sampler tests pass, but driver-loop lag is not application-loop lag; profile documents the limitation. |
| Kill/restart during active physical work, drain/fencing/recovery without loss/duplication | **UNVERIFIED.** No active-Attempt production kill/restart experiment executed this round. Exit/rejoin and terminal Run counts alone are insufficient. |
| Long-running exact RC/configuration soak; rerun after runtime changes | **NOT MET by evaluated evidence.** Duration 420.08 < 14,400 seconds. `scripts/soak/run_soak.py:730-741` explicitly excludes this host-process driver from exact-RC certification. |
| Findings filed/reclassified to earliest broken milestone before promotion | **UNVERIFIED for completeness.** Existing local findings retained; this report preserves blockers. Backlog consistency is not filing-completeness proof; no GitHub mutation performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for the promotion RC.** Historical JSON and human report exist, but host-process evidence cannot establish immutable promoted-image/configuration identity. |

## Handoff

Only this report changes. No source or test changes were justified by the
reproduced CI evidence. No tests added, so no inventory-delta note is required.
No ledgers, grants, gates, runtime configuration, or historical evidence changed.

Next: select immutable RC/configuration, resolve the aggregate rate-limit
contract, complete representative production workloads and physical-work /
recovery / application-telemetry oracles, then execute and publish a >=4-hour
exact-artifact soak. Repeating the stale schema failure or a clean vulture scan
cannot resolve these prerequisites. A longer run of the existing emulator
also cannot pass its explicit artifact gate.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: production acceptance prerequisites}.
The focused CI investigation is complete; the issue's production acceptance is not.
