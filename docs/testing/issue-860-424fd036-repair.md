# Issue #860 — repair checkpoint (424fd036)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`ca9ca1f2224c584d35db0b929296bfb183fbeca7`, supplied base
`2154f845347c9541016288c760f8da3f5cd2e064`. Initial worktree clean.
No GitHub mutations or re-enumeration of campaign items.

Review inputs: supplied dispatch-context.json, prior result.json, reported
check-3.log, repository instructions, relevant ADRs, soak runner/profile/tests,
and vulture gate/workflow/ledger. Candidate edits limited to this note and
`quality/vulture-baseline.json` if the exact scan establishes retained debt.
No production change without actual evidence and a scope checkpoint.

Ambiguity: supplied base diff contains substantial inherited unrelated history;
it is not treated as a request to undo or repair other lanes. This is a writer
repair round, not the read-only verifier role. Previous BLOCKED verdict is an
unverified claim until fresh checks run. No check-*.log files exist in this job's
initial directory listing; inspect the explicitly supplied prior failure log.

## Fresh results (checkpoint 1)

- Captured issue body has ten acceptance criteria; all assessed below before handoff.
- Historical check-3.log reports schema-test mismatch (24 DDL statements versus
  21), not a vulture violation.
- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed; 1323 findings / 1323 reviewed identities, zero unclassified and
  never-allowlist findings. Scanner uses base `3c761d14db94`, candidate
  `ca9ca1f2224c`. No retained unbanked identity exists to amend in this round.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce. Skipped live-DB
  tests do not establish multi-replica PostgreSQL safety.

## Fresh results (checkpoint 2)

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  73 passed.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `uv run python scripts/check-deployment-claims.py`: passed (static presence
  validation, not deployed topology certification).
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified /
  19 discovered lifecycles.

Commands used a 1200-second timeout. No full-tree pytest or live soak ran.

## ADR reconciliation

Read repository instructions, docs authority map, ADR-085, ADR-081226-a66b,
ADR-081626-f383, ADR-082526-b36a, ADR-082826-08f0, and proposed ADR-081.
The earlier handoff's claim that reclaim is deferred must not be used as current
policy: accepted b36a defines TTL/renewal/reclaim, and 08f0 defines the shared
recovery disposition table (including refusal to steal live leased work).
An admission-only race cannot prove those physical execution guarantees.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and canonical lifecycle /
event authorities. Proposed deployment text cannot waive issue acceptance.
ADR-085 specifies per-principal rate limiting but does not supply a shared
cluster-budget implementation. No new scheduler, store or authorization path
is introduced here.

## Production reachability and evidence limits

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:104–122`
  includes the three Gauntlet audit columns absent from the historical failure's
  expectation. `ensure_schema` takes its advisory lock before DDL at lines
  215–220. The fresh passing test independently lists those columns at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the real
  rate middleware; `api/rate_limit.py:90–98` creates its in-memory limiter.
  The executed test at `tests/test_soak_promotion_gates.py:439` observes
  `[200, 200, 429]` independently on two instances for the same identity,
  authenticated and unauthenticated. This falsifies shared allowance, but
  is not a deployed two-replica soak or proof of other security controls.
- `packages/maistro-server/src/maistro_server/api/tasks.py:117` maps Run
  ceiling rejection to 429 with Retry-After. The executed route regression
  uses real canonical admission wiring and demonstrates principal isolation
  and renewed admission after a slot frees. It deliberately starts no worker.
- `scripts/soak/run_soak.py:744–755` refuses to certify its host-process
  topology as exact RC evidence. Executed CLI regression at
  `tests/test_soak_promotion_gates.py:103` refuses otherwise-passing synthetic
  four-hour evidence without a valid artifact check.
- `scripts/soak/run_soak.py:1067–1092` cancels the schedule probe Run without
  executing it. Admission uniqueness cannot establish physical-work fencing.
- `deploy/docker-compose.prod.yml:10–12` labels the topology a reference
  artifact requiring digest pinning. Two service definitions alone cannot
  prove two deployed replicas or select the final promotion artifact.

## Acceptance matrix (all ten captured criteria)

| Criterion | Executed evidence / disposition |
|---|---|
| Representative RC profile: users/Workspaces, mix, fan-out, schedules, queue, tools/models, Design/Canvas, background workers | UNVERIFIED. Reviewed `m3a-load-profile.md`: preflight uses one key and explicitly lacks several required surfaces; selected RC configuration must justify any exclusions. |
| At least two deployed application replicas | UNVERIFIED. Middleware instances are not deployed replicas; no fresh deployment executed. |
| Sustained saturation, queues, expiry/reclaim, retries/backoff, memory/descriptor/process leaks and restart | UNVERIFIED. No sustained RC load window executed; passing bounded tests are not a soak. |
| Schedule/task/Run/Attempt/Goal uniqueness and physical-work fencing | UNVERIFIED. Current claim probe only races admission and cancels its unexecuted Run; unit tests do not demonstrate cross-replica physical work under load. |
| Rate/security/degraded behavior cannot be bypassed through replica selection | Independent rate allowance reproduced by executed production middleware regression above. Non-bypass criterion is not satisfied by local 429s; deployed security/degraded behavior UNVERIFIED. |
| PostgreSQL usage/latency/locks, app event-loop, worker/process/RSS/descriptors, queues/errors/timeouts with explicit thresholds | UNVERIFIED. Profile acknowledges driver-loop versus application-loop mismatch and missing production-grade metrics; no fresh telemetry series. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. No active physical Attempt restart performed; rejoining health is insufficient under accepted recovery ADRs. |
| Long soak of exact RC artifact/configuration, rerun on changes | UNVERIFIED. Host runner fails artifact certification by design; reference Compose is not an immutable designated RC. No four-hour exact-RC soak executed. |
| Findings filed/reclassified at earliest broken invariant | Partial only: `BACKLOG.md:267–279` records engine-116 as gap-spec; backlog gate passes. Completeness against a representative RC soak remains UNVERIFIED. No GitHub mutations. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED. This report identifies source HEAD, not an RC image/config evidence pack. |

## Disposition and handoff

BLOCKED for issue acceptance. The historical failing schema assertion is already
repaired, and the exact requested vulture scan has no unbanked identities.
Changing code or the ledger without new failure evidence would be speculative.
Only this report changes. No new tests or test-count changes; inventory delta
is zero and no inventory note is required. No gates, ledgers, grants or inherited
work were altered. No conflict exists to resolve; no fetch/merge was warranted.

Required next actions: designate immutable RC artifact/configuration and workload
coverage; resolve engine-116 through the existing limiter seam; instrument the
application and execute at least the profile's four-hour exact-RC window with
active physical work, restart, reclaim and stale-writer evidence. Do not redispatch
the already-passing schema test as a new repair. Local unit/gate success is not
promotion evidence or integration approval.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands; next: RC prerequisites and production soak.
Local validation/handoff complete; commit required before final response.
