# Issue #860 — 5b3209a1 repair checkpoint

## Frozen scope

- Assigned issue only: #860, branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting clean HEAD: `330dcfdd0ab86ecad121619c120d0a3e706a5a57`.
- Supplied base `435dc1937e0407ab4de198ffcced49860bb14ad2` resolves locally.
- Evidence snapshot: `/home/dev/maistro/jobs/5b3209a1b63c4ffa8483a1782370dd33/dispatch-context.json`.
- Planned edit: this report only; conditional vulture-ledger repair only if the required scan demonstrates an actual unbanked identity. No new tests or inventory changes planned.
- No current-job `check-*.log` existed at initial directory inspection. The supplied historical `98a11313167b41a98a420abfda80c292/check-3.log` is a schema-test failure (24 DDL statements versus 21 expected), not a vulture failure.

Assumption: writer repair does not authorize selecting an RC on behalf of the release owner. Missing immutable artifact/configuration and workload applicability cannot be replaced by a host-process emulator run. No GitHub mutations, merges, alternate runtime authorities, or gate weakening are in scope.

## Fresh results

The exact mandated command ran successfully:

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

Result: 1323 findings / 1323 reviewed identities, zero unclassified or forbidden identities. Gate-selected base: `4aa68edc0b6b`. No ledger amendment is justified; the conditional ledger repair is skipped as unnecessary. A workflow discovery glob `.github/workflows/*inventory*` did not match; recorded as not found, not a validation failure.

Read accepted ADR-081226-69ee (canonical Graph/Run/NodeRun/Attempt), ADR-081626-f383 (execution fencing), ADR-082526-b36a (renewal/reclaim), and ADR-085 (per-principal limits). The later renewal contract supplements the earlier fence boundary; replica restart does not permit cancelling another live holder. Per-principal identity alone does not establish a shared replica budget or waive #860's non-bypass acceptance.

## Executed validation

Commands ran in the assigned worktree with 1200-second validation timeouts. Results below are fresh, not inherited verification claims.

| Command | Result |
| --- | --- |
| Mandatory vulture command above | PASS; 1323/1323 reviewed identities |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | PASS; 103 passed, 6 skipped in 2.68s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files already formatted |
| `uv run python scripts/check-deployment-claims.py` | PASS; component/backend existence, not deployment certification |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check` | PASS |

All six skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated database. They do not prove live PostgreSQL safety. The historical 24-versus-21 schema failure is absent: the current independent expected DDL list includes validation audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173–175`. The test verifies all 24 statements inside one transaction after the advisory lock, matching the production fence at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:216`. No test was added or modified; inventory delta is zero.

## Acceptance review

| Issue criterion | Reachable behavior / executed evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:151–170` identifies absent concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background reconciliation. Applicability for a selected RC is not established. |
| At least two deployed application replicas | **UNVERIFIED.** `deploy/docker-compose.prod.yml:26–78` declares two servers; this round did not run an immutable RC deployment. ASGI middleware instances are not deployed replicas. |
| Sustained saturation, queue growth, reclaim, retries, memory/descriptor/process leaks and shutdown | **UNVERIFIED.** The 2.68-second regression suite is not sustained traffic or a production time series. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED.** `m3a-load-profile.md:193–203` limits the schedule probe to one occurrence cancelled without execution. Receipt tests exercise admission evaluation, not distributed physical-work uniqueness. |
| Rate/security/degraded non-bypass across replicas | **UNVERIFIED at release scope; independent allowances reproduced.** `tests/test_soak_promotion_gates.py:439` passes by observing `[200, 200, 429]` on each real middleware instance for the same identity. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; its state is allocated per instance at `api/rate_limit.py:93`. Local enforcement cannot prove the required non-bypass property. The task concurrency/backpressure regression also passes but is not a distributed security soak. |
| Complete telemetry and explicit thresholds | **UNVERIFIED for RC.** The profile documents thresholds and missing application-loop/worker, pool-saturation and long-window observations. Driver-loop lag is not application-loop latency. No new production telemetry was collected. |
| Active-work kill/restart with graceful drain/fencing/recovery | **UNVERIFIED.** No deployed-RC fault injection in this round. Process rejoin and terminal row counts alone do not establish absence of physical loss or duplication. |
| Long-running exact RC/config soak, rerun after runtime changes | **UNVERIFIED / BLOCKED.** No immutable RC/config designation was supplied in the assignment. The current host runner explicitly returns `exact_rc_artifact.ok=false` at `scripts/soak/run_soak.py:730–741`. The executed CLI regression at `tests/test_soak_promotion_gates.py:106` rejects synthetic four-hour records with absent/null/preflight identity; it did not execute a four-hour soak. |
| Findings filed/reclassified before promotion | Local limitations recorded here; external filing/reclassification **UNVERIFIED**. No GitHub mutation is authorized. No new sustained-load finding was generated. |
| Machine/human soak evidence bound to exact image/package/commit/config | **UNVERIFIED for RC.** This report binds regression observations to the starting source HEAD, not to an executed RC image/config. No new long-running machine evidence exists. |

The captured latest issue comments and draft PR #1672 body contain no new RC designation; they record prior blocked attempts and a claim-stake draft. They are evidence, not authorization. Historical soak artifacts are not recertified by this report.

## Handoff

**BLOCKED.** The requested CI symptoms do not reproduce, so speculative source edits or ledger changes would not repair actual evidence. Only this report changed; source, tests, inventory and quality ledgers remain untouched. No conflict or incoming uncommitted work required salvage. The inherited branch is not certified as merge-ready by these focused checks.

Next prerequisite: the release owner must supply the immutable RC/config and supported workload applicability. Complete production-path traffic/telemetry and physical-work/recovery observations, reconcile the replica-selection non-bypass gap through canonical security, then execute the required long soak and publish hash-bound evidence. Do not substitute another four-hour host emulator run or relax promotion gates.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`. The local report commit is the checkpoint, not issue completion or integration approval.
