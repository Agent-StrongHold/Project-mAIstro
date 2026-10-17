# Issue #860 repair checkpoint — 082d1ff1

## Scope and disposition

**BLOCKED; not integration approval.** Inspected issue #860 from the supplied
`dispatch-context.json` snapshot only, starting at
`7a73be0591083ee6e57721140db37d2e9a7b5fcb` on `auto-860`, supplied develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Initial worktree was clean.
No current-job `check-*.log` files were present. Read the supplied prior result
and `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
That historical failure expected 21 schema statements but observed 24.

Frozen repair targets were that schema-fence regression, the mandated vulture
ledger check, and this handoff. Read their production/test surroundings plus
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, the load profile,
production Compose topology and installed rate middleware to assess acceptance.
Assumption: CI repair does not authorize inventing an RC designation or changing
execution/security architecture. No GitHub mutations or ref updates performed.

## Fresh executed evidence

Commands ran in the assigned worktree with 1800-second validation timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings; zero unclassified or forbidden identities; gate-selected base `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 103 passed, 6 skipped in 2.55s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3270 files formatted |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 31128 unique identities, no duplicate evidence |
| `uv run python scripts/check-deployment-claims.py` | PASS: component existence only, not deployed behavior |
| `git diff --check` | PASS |

All six skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated database;
this run supplies no live PostgreSQL evidence. The current test independently
lists all 24 DDL statements, including audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:173–175`.
The production transaction/advisory fence is at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`.
The reported CI failure no longer reproduces. No dead-code or unbanked-identity
finding justifies a ledger amendment. Only this report changed; no tests added
or modified, so inventory delta is zero.

## Architecture and acceptance

Read repository instructions, documentation authority map and accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. The canonical Run store owns
Attempt authority; lease renewal/reclaim supplements fencing and does not permit
restart-based cancellation of another live holder. Per-principal identity does
not itself establish a shared rate allowance. No competing authority introduced.

| #860 criterion | Evidence / remaining requirement |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** `m3a-load-profile.md:151–170` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background reconciliation. Selected-RC applicability is not supplied. |
| Two deployed application replicas | **UNVERIFIED.** `deploy/docker-compose.prod.yml:26–78` defines two services; no RC deployment was executed here. |
| Sustained saturation, queues, reclaim, retries, leaks and shutdown observations | **UNVERIFIED.** A 2.55-second regression run is not sustained production load; no new time series collected. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED.** Receipt tests prove admission evidence checks, not physical-work uniqueness. The profile's schedule probe cancels its Run without execution (`m3a-load-profile.md:193–203`). |
| Rate/security/degraded non-bypass by replica selection | **Counterexample reproduced.** `tests/test_soak_promotion_gates.py:439` tests the same identity on two production middleware instances: each independently returns `[200, 200, 429]`. `api/rate_limit.py:93` allocates per-instance in-memory state; `maistro_server/main.py:648` installs it. This is not a full deployed security soak. Cluster-wide non-bypass remains unproven. |
| Complete telemetry and explicit thresholds | **UNVERIFIED for RC.** Documented thresholds and sampler tests do not provide deployed application-loop/pool/worker telemetry; driver-loop lag is not application-loop lag. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** No RC fault injection; missing-drain rejection tests do not prove physical recovery. |
| Long exact-RC/config soak, repeated after changes | **BLOCKED / UNVERIFIED.** No immutable RC/config designation supplied. `scripts/soak/run_soak.py:730–741` explicitly rejects host preflight as exact-RC evidence. Executed CLI tests reject synthetic four-hour evidence with missing/null/preflight identity; they do not execute four hours of load. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification **UNVERIFIED**. GitHub mutation prohibited. |
| Machine/human evidence bound to exact image/package/commit/config | **UNVERIFIED for RC.** This report identifies the regression source revision, not a promoted image/configuration. Historical evidence is not recertified. |

## Resume condition

Do not repeat this CI-repair loop against the same historical failure: the exact
vulture gate and reported schema test pass. Resume substantive #860 work once an
immutable RC/configuration and workload applicability are supplied, with a plan
for production workloads, shared rate enforcement, physical-work recovery probes
and complete telemetry. Then run the long soak and publish hash-bound evidence.
A longer host-process preflight cannot meet the exact-artifact criterion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
