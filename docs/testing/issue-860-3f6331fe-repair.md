# Issue #860 — repair validation 3f6331fe

## Scope and decision

One frozen item: #860 and its explicitly assigned vulture CI repair. Starting
HEAD: `60960671f26b29db8b1ffd4919da6fd030c5949b`; assigned base:
`2154f845347c9541016288c760f8da3f5cd2e064`. The assigned worktree was clean.
No sync conflict or uncommitted salvage existed. No GitHub mutations performed.

Current job directory had no driver `check-*.log` files. Read the supplied
prior result and the historical `98a11313167b41a98a420abfda80c292/check-3.log`:
the latter reports 24 schema statements against 21 expected. Fresh execution
below does not reproduce it. The test already independently includes the three
Gauntlet audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`.

Fresh exact-scope vulture scan reports **1323 reviewed identities / 1323
findings**, with zero unclassified or never-allowlist findings. Therefore no
ledger amendment or speculative dead-code removal is justified. The only edit
in this round is this evidence report. No tests changed or added; no inventory
delta or inventory note is required.

## Architecture reconciliation

Read repository instructions, documentation authority map, quality gates,
accepted ADR-081226-a66b, ADR-081626-f383, ADR-082526-b36a,
ADR-082826-08f0 and ADR-085, plus the existing load profile, production middleware,
schema upgrade, soak gate and adjacent tests. Later accepted renewal/recovery
ADRs extend the original fencing boundary: live leased work cannot be stolen;
expired work is reclaimed through the canonical lifecycle seam. Admission-only
counts are not physical-work or recovery proof. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt without another scheduler,
authorization path or execution authority.

## Fresh validation

All commands used 1200-second tool timeouts. Logs are in job directory
`/home/dev/maistro/jobs/3f6331fe0c4a47aeb63fe4ed7752adee/` under `worker-*.log`.

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323/1323 identities.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped** (live PostgreSQL coverage not established).
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`: **93 passed**.

- `uv run python scripts/check-deployment-claims.py`: passed (static component/backend existence only).
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified / 19 discovered.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `git diff --check`: passed.

Production reachability was checked at
`packages/maistro-server/src/maistro_server/main.py:648`, which installs the
same `RateLimitMiddleware` used by the executed replica-selection regression.
`BACKLOG.md:267` records engine-116 as Accepted with `gap-spec`; the passing
backlog gate is structural validation, not closure of the cluster-budget gap.

The extra execution-fencing and recovery-disposition tests exercise canonical
services, including bounded durable recovery; they do not establish production
multi-replica recovery under sustained load. No live deployment or long soak was
run, and no immutable RC/configuration was designated by this assignment.

## Acceptance matrix

| # | Criterion | Executed evidence or explicit gap |
|---|---|---|
| 1 | Representative RC workload | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` explicitly lacks multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and sustained Goal/background workloads; no selected RC exclusion justification supplied. |
| 2 | Two deployed application replicas | UNVERIFIED. ASGI middleware instances are not deployed replicas. |
| 3 | Sustained saturation, queue growth, reclaim, retries, leaks and restart | UNVERIFIED. Bounded tests are not a sustained observation window. |
| 4 | No duplicated physical work; schedule/task/Run/Attempt/Goal fencing | UNVERIFIED under load. Focused fencing/recovery tests pass, but admission-only probes cannot prove physical-work uniqueness or Goal reconciliation. |
| 5 | Rate/security/degraded enforcement cannot be bypassed by replica selection | NOT SATISFIED at the middleware seam. Executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both instances for the same identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs a local limiter. Deployed security/degraded behavior remains UNVERIFIED. |
| 6 | Full telemetry with explicit thresholds | UNVERIFIED. No fresh production series for PostgreSQL usage/query latency/locks, application-loop latency, workers/processes/RSS/descriptors/queues/errors/timeouts. Driver-loop lag is not application-loop latency. |
| 7 | Active-work kill/restart, graceful drain, fencing and recovery | UNVERIFIED. Bounded recovery tests pass, but no deployed active Attempt was killed/restarted during sustained traffic. |
| 8 | Long soak of exact RC artifact/configuration | UNVERIFIED. `scripts/soak/run_soak.py:744` deliberately refuses host-preflight certification; executed CLI regression at `tests/test_soak_promotion_gates.py:103` rejects otherwise-passing synthetic four-hour evidence without the RC artifact record. |
| 9 | Classify findings to earliest broken invariant | UNVERIFIED for completeness without representative load. Existing engine-116 tracks the shared-budget gap; no new live findings or GitHub filings in this round. |
| 10 | Machine/human evidence bound to exact artifact/config hashes | UNVERIFIED. These logs and this source-HEAD report are not an image/package/config-bound production soak pack. |

## Handoff

Issue acceptance remains **BLOCKED**, not merge-ready. CI failures supplied to
this round are stale or not reproducible at the assigned HEAD; changing passing
expectations or banking guessed scanner identities would not repair acceptance.
Next: designate the immutable RC image/configuration and representative profile;
resolve the cluster-wide rate-budget gap through the existing limiter seam;
execute the minimum four-hour production soak with full application telemetry,
active physical work, kill/restart, reclaim and stale-writer evidence. Do not
substitute another host-preflight run for this requirement.

Progress: checked 1, acceptance-complete 0, skipped issues 0, validation errors 0.
Local handoff only; no integration approval or issue closure.
