# Issue #860 — fresh CI-repair validation (f953d9ae)

## Scope and decision

Assigned worktree `auto-860`, clean starting head
`bf3fa1a71f9a342814d8fc510412d07f75ab0912`, supplied develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Frozen scope: issue #860 only,
its existing soak/profile/tests, reported schema-fence failure, exact vulture
gate, and this report. No GitHub mutations, refresh, merge, or runtime changes.

**BLOCKED for issue acceptance.** The historical failure in job
`98a11313167b41a98a420abfda80c292/check-3.log` does not reproduce. The current
job directory contained no driver `check-*.log` files. The supplied prior result
and captured issue evidence were inspected, but passing claims below come from
fresh execution. There is no observed CI defect to repair or unbanked identity
to review/amend. Changing the ledger or weakening tests would be unjustified.

Read repository instructions and accepted ADR-081226-69ee (Graph execution),
ADR-081626-f383 (Attempt fencing), ADR-082526-b36a (renewal/reclaim), and ADR-085
(principal rate limits). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
Admission receipts cannot substitute for physical-work fencing; restarting one
replica does not confer authority to reclaim another live holder. Principal
identity does not imply shared limiter state. No competing execution or security
authority was introduced.

## Executed validation

Logs are in `/home/dev/maistro/jobs/f953d9aee26743caa44f9c574b7ebca2/`.
Timeouts were 1200 seconds for vulture and 1800 seconds for tests/other gates.

| Command | Fresh outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings, zero unclassified/forbidden; gate-selected base `4aa68edc0b6b`. `repair-vulture.log`. Arguments match `.github/workflows/quality.yml:1078`. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 103 passed, 6 skipped in 2.64s. `repair-targeted-tests.log`. Skips require a migrated `MAISTRO_TEST_PG_DSN`; no live database validation claimed. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3270 files. |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 31128 unique identities, zero duplicates. |
| `uv run python scripts/check-deployment-claims.py` | PASS: existence check only, not deployed-runtime proof. |

The last four commands are recorded in `repair-gates.log` with exit codes zero.
The schema regression independently asserts all 24 ordered DDL operations under
the advisory lock (`test_pg_learnings.py:132–194`); production takes the lock
inside the transaction (`pg_learnings.py:215–216`). No test or inventory changes,
no ledger/grant amendment. This report is the only changed file.

## Acceptance checked against reachable behavior

| Criterion | Disposition and evidence |
| --- | --- |
| Representative RC workload | **UNVERIFIED**: `m3a-load-profile.md:151–170` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background reconciliation. No RC-specific applicability established here. |
| Two application replicas | **UNVERIFIED at runtime**: `deploy/docker-compose.prod.yml:26–78` defines two servers, but this round did not deploy a designated RC. |
| Sustained saturation, queue/reclaim/retry and leak observation | **UNVERIFIED**: the 2.64-second regression run is not a sustained-load experiment; no new telemetry time series. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | **UNVERIFIED**: profile lines 193–203 describe a single schedule admission race cancelled before execution, not physical-work uniqueness under sustained load. |
| Rate/security/degraded non-bypass by replica selection | **Not satisfied**: executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439–489`) accepts two requests on replica 2 after replica 1 exhausts the same identity's allowance, for authenticated and unauthenticated clients. This exercises production middleware, not a full deployed security soak. `api/rate_limit.py:93` creates an in-memory limiter per instance; `maistro_server/main.py:648` installs it. |
| Complete telemetry and pass/fail thresholds | **UNVERIFIED for RC**: documented thresholds and sampler tests do not supply application-loop, worker, PostgreSQL, queue and leak measurements for a designated RC. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**: fail-closed promotion-gate tests pass, but no active-work fault injection ran. |
| Long soak of exact RC/config, repeated after changes | **UNVERIFIED / prerequisite blocked**: no immutable promotion artifact/configuration is designated in the lane assignment. `scripts/soak/run_soak.py:730–741` deliberately rejects host-process preflight as exact-RC evidence; executed CLI tests enforce that rejection. A longer emulator run cannot satisfy this criterion. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification **UNVERIFIED**, with GitHub mutation prohibited. |
| Hash-bound machine/human soak evidence | **UNVERIFIED for RC**: this source-bound validation report and local command logs are not a promotion soak bundle. Historical artifacts were not recertified. |

## Handoff

No speculative repair was made. Supply the immutable RC/configuration and its
representative workload, resolve the replica-selection rate-budget gap through
the existing enforcement path, and provide production physical-work/recovery
probes before executing the long soak with complete telemetry and hash-bound
artifacts. This is not integration or promotion approval. Repeating passing CI
checks cannot resolve the release-evidence blocker.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
