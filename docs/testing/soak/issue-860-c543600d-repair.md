# Issue #860 bounded repair — c543600d

## Frozen scope

Only issue #860, branch `auto-860`, starting clean at
`b65ef7f494efbac9e557a5e0445f47927f607797`; supplied base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Use the supplied dispatch snapshot;
no GitHub refresh or mutation. No current-job `check-*.log` files were present.
Read the supplied prior result and historical `98a11313.../check-3.log`.

Repair targets: the reported schema-fence test in
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`, the mandated
`quality/vulture-baseline.json` gate, and this report. Acceptance inspection is
limited to the existing soak profile/driver/tests, production Compose and rate
middleware, relevant ADRs and adjacent tests. Change code/ledger only if fresh
execution supplies an actual finding. Do not fabricate an RC designation or
replace canonical execution/security authority to satisfy issue wording.

Fresh results: the historical 21-versus-24 DDL failure does not reproduce.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
passed **103 tests, 6 skipped in 2.60s**. All skips require a migrated
`MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof is claimed.

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
passed: **1323 reviewed identities / 1323 findings, zero unclassified or
forbidden identities** (gate-selected base `4aa68edc0b6b`). No evidence justifies
a code or ledger amendment. Both commands used 1800-second timeouts.
No new tests are warranted for a non-reproducing failure.

Additional fresh validation (1800-second timeout):

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites, 31128 unique identities, zero duplicates |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence, not runtime proof |
| `git diff --check` | PASS |

Only this report changed. No test additions/modifications or inventory delta;
no ledger/grant edits.

## Architecture and acceptance disposition

Read repository instructions and accepted ADR-081226-69ee (Graph execution),
ADR-081626-f383 (Attempt fencing), ADR-082526-b36a (renewal/reclaim), ADR-085
(principal rate limiting). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`:
Run-store lease authority cannot be replaced by a soak scheduler, and restarting
a replica cannot imply every other holder is dead. Per-principal rate identity
alone does not mean a cluster-wide allowance. No architecture changed.

| #860 acceptance | Fresh evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:151–170` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background reconciliation. Applicability to a designated RC is not supplied. |
| At least two application replicas | **UNVERIFIED.** `deploy/docker-compose.prod.yml:26–78` defines two replicas, but no designated RC deployment was run. |
| Sustained load observing saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** The 2.60-second regression run is not a sustained load experiment; no fresh time series. |
| Physical-work uniqueness across schedules/task/Run/Attempt/Goal | **UNVERIFIED.** Admission receipt checks do not prove physical execution uniqueness; `m3a-load-profile.md:193–203` documents a one-occurrence probe cancelled without execution. |
| Rate/security/degraded non-bypass by replica selection | **Counterexample reproduced**, not satisfied: `tests/test_soak_promotion_gates.py:439–489` uses production middleware with identical client identity and observes `[200, 200, 429]` independently on each replica. `api/rate_limit.py:93` allocates an in-memory limiter per instance; `maistro_server/main.py:648` installs it. This test is not a full deployed security soak. |
| Complete PostgreSQL/application/worker/queue/error telemetry with thresholds | **UNVERIFIED for RC.** Profile thresholds and sampler tests exist, but driver-loop latency is not application-loop latency and no new deployed telemetry was collected. |
| Active-work kill/restart and drain/fencing/recovery | **UNVERIFIED.** Gate tests reject missing/null drain evidence; no active RC workload was fault-injected. |
| Long soak of exact RC/config, repeated after changes | **BLOCKED / UNVERIFIED.** Dispatch does not designate an immutable promotion image/config. `scripts/soak/run_soak.py:730–741` rejects host-process preflight; executed CLI regression tests reject synthetic four-hour evidence with missing/null/preflight identity. They do not execute four hours of load. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification **UNVERIFIED**. GitHub mutation prohibited. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC.** This source-bound local report is not an RC evidence bundle; historical soaks are not recertified. |

## Handoff

**BLOCKED**, not merge/integration approval. Historical CI failure is resolved
in the starting tree, and the required ledger gate passes without amendment.
Remaining work is substantive release evidence, not another speculative CI fix.
Supply an immutable RC/configuration and workload applicability; establish shared
rate enforcement and production physical-work/recovery probes; then execute the
long soak with full telemetry and hash-bound machine/human artifacts. A longer
host preflight cannot meet these criteria. Six database integration tests were
skipped; do not interpret this run as live PostgreSQL validation.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designated RC and production-soak prerequisites"}`.
