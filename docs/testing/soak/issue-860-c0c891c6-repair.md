# Issue #860 focused repair — c0c891c6

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD `3961de784288cdf67c118060b6ae4b79d493c6ae`, supplied develop base `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Clean initial worktree; no salvage needed. No current-job check logs supplied.
- Inspect the supplied dispatch snapshot and prior result/log, relevant repository instructions/ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, and its adjacent tests.
- Potential edits limited to the reported schema-fence test, its inventory note, this report, and `quality/vulture-baseline.json` only if the mandated scan proves retained unbanked identities.
- Execute focused tests, lint/format, mandated vulture scan and relevant inventory gate. No GitHub mutation, release designation, new execution authority, or unrelated repairs.

## Initial evidence and assumption

The supplied prior check-3 log failed the schema-fence test (24 DDL statements versus 21 expected). The supplied prior result reports BLOCKED for absent exact-RC soak evidence. Both claims require fresh validation. Assumption: this is a focused CI-repair round, not authority to designate a release candidate or replace the scheduler/rate-limit architecture.

## Fresh checkpoint

The mandated vulture scan passed: 1323 reviewed identities / 1323 findings, zero unclassified or forbidden identities (gate-selected base `4aa68edc0b6b`). No ledger edit is justified. The current schema test already explicitly includes the three validation-audit columns absent from the historical failed log; focused execution is next. No release artifact/configuration was supplied in the assignment. Acceptance remains unproven for the reasons below.

## Executed validation

All validation commands used 1800-second timeouts in the assigned worktree.

| Command | Fresh outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323 identities; no ledger amendment needed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 103 passed, 6 skipped, 2.55s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | PASS; all 17 suites match, 31128 unique identities, no duplicate evidence |
| `uv run python scripts/check-deployment-claims.py` | PASS; existence check, not deployment certification |
| `git diff --check` | PASS |

The six skips explicitly require `MAISTRO_TEST_PG_DSN` pointing at a migrated database. They are not live PostgreSQL evidence. The historical check-3 failure is already repaired in the starting tree: `packages/maistro-core/tests/persistence/test_pg_learnings.py:173–175` independently enumerates the three audit columns, and the passing test checks all 24 DDL statements after the advisory lock inside one transaction. Production uses that fence at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:216`. No tests were added or changed; inventory delta is zero.

## Architectural reconciliation

Read repository AGENTS.md, the documentation authority map, and accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a, and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; physical Attempt authority belongs to the canonical Run store. The later renewal/reclaim ADR supplements the initial fence boundary; restart is not authority to cancel another live holder. Per-principal identity under ADR-085 does not establish a shared replica allowance and does not waive #860's explicit non-bypass requirement. No competing scheduler, authorization, state store, or execution path was introduced.

## Acceptance review

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative supported RC profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:151–170` documents absent concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas, and background reconciliation. Selected-RC applicability remains unspecified. |
| At least two deployed application replicas | **UNVERIFIED.** `deploy/docker-compose.prod.yml:26–78` declares two services; configuration existence and two ASGI middleware instances are not an executed RC deployment. |
| Sustained saturation, queue growth, reclaim, retry/backoff, memory/descriptor/process leaks and shutdown observations | **UNVERIFIED.** The 2.55-second regression run is not sustained production traffic. No new load time series was collected. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED.** Executed receipt tests assert canonical admission identities, not physical-work uniqueness. The profile at lines 193–203 limits its schedule probe to an occurrence cancelled without execution. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven; a production-middleware counterexample is reproduced.** `tests/test_soak_promotion_gates.py:439` obtains `[200, 200, 429]` independently on each instance for the same credential/IP. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:93` allocates an `InMemoryRateLimiter` per instance. Cluster-wide enforcement and other security/degraded behavior remain **UNVERIFIED**. |
| Required PostgreSQL, application-loop, worker, RSS, descriptor, queue, error/timeout telemetry and thresholds | **UNVERIFIED for RC.** The documented thresholds do not supply missing application-loop/pool/worker observations. Driver-loop latency is not application-loop latency. |
| Active-work kill/restart with graceful drain/fencing/recovery | **UNVERIFIED.** No deployed-RC fault injection this round. Gate tests reject omitted drain records; they cannot prove no physical loss or duplication. |
| Long soak of exact RC/config, repeated after runtime changes | **BLOCKED / UNVERIFIED.** No immutable RC/config was supplied. `scripts/soak/run_soak.py:730–741` always rejects its host-process preflight as exact-RC evidence. The executed CLI test at `tests/test_soak_promotion_gates.py:106` rejects synthetic four-hour evidence with missing/null/preflight identity; it does not run a four-hour soak. |
| Load findings filed/reclassified before promotion | Local findings recorded here; external filing/reclassification **UNVERIFIED**. No GitHub mutation authorized or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** This report identifies the source HEAD for regression checks, not an executed release image/config. Historical machine artifacts are not recertified. |

## Handoff

**BLOCKED.** The requested schema/vulture CI symptoms do not reproduce. Changing passing source, tests, or ledger identities would be speculative rather than evidence-based repair. Only this report changed. All inherited work is preserved; no conflicts or dirty incoming changes required salvage.

Next: release owner supplies immutable RC/config and workload applicability; close the shared rate-enforcement gap through the canonical security path; complete production workloads, physical-work/recovery probes and telemetry; execute the required long soak and publish hash-bound evidence. Repeating host-preflight runs cannot satisfy the exact-RC requirement. This local report commit is a checkpoint, not integration approval or issue completion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
