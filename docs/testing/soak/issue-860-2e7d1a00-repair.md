# Issue #860 — repair round 2e7d1a00

## Frozen scope

- Assigned issue only: #860; branch `auto-860`.
- Verified clean starting HEAD: `b09cece3ee1efc14b430bfb8ac75833a30457806`.
- Supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Process the supplied dispatch snapshot and prior check-3.log; no GitHub mutations or refreshed issue lists.
- Review files: repository instructions, relevant execution/production ADRs,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, CI gate implementation/workflow,
  and the prior handoff `issue-860-b121f2c8-repair.md`.
- Candidate edit scope: this report; `quality/vulture-baseline.json` only if
  the mandated scan identifies reviewed retained identities. No speculative
  source changes or unrelated merge work.
- Current job directory contains no check-*.log files at initial inspection.
- Ambiguity: prior result is BLOCKED, not evidence of a merge conflict.
  Assume no develop merge is requested unless actual conflict evidence appears.

## Validation checkpoint

- Mandated exact vulture scan: exit 0; 1323 reviewed identities / 1323 findings,
  zero unclassified. No ledger amendment is justified by the current scan.
- Focused pytest covering the reported schema failure, soak promotion gates,
  production boot and task backpressure: exit 0 (details below after log review).
- `uv run ruff check .` and `uv run ruff format --check .`: both exit 0.
- The historical schema failure expected 21 DDL operations. The current test
  independently includes all 24, including the three validation-audit columns.
- Logs are `validation-{vulture,tests,ruff,format}.log` in the supplied job directory.

## Executed validation

All validation used the assigned worktree and 1200-second command timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323 reviewed identities match 1323 findings; CI arguments verified in `.github/workflows/vulture-ratchet.yml:82` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 111 passed, 6 skipped in 2.47 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files |
| `uv run python scripts/check-suite-inventory.py` | PASS; `validation-inventory.log` |
| `uv run python scripts/check-deployment-claims.py` | PASS; `validation-deployment.log` |
| `git diff --check` | PASS |

The six skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated database.
They are not live PostgreSQL proof. The stale check-3.log failure is not present
in the starting tree: the schema test executes the real `ensure_schema` against
an observing fake connection, checks lock/transaction ordering and independently
checks all 24 DDL statements. No test, production code or ledger edit is justified
by these results. No new tests were added, so no inventory delta is needed.

## Acceptance audit against reachable behavior

| Issue criterion | Fresh evidence and disposition |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED.** Profile exists, but `m3a-load-profile.md:152` explicitly lists missing multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. The actual runner mix at `scripts/soak/run_soak.py:1381` remains health/task/degraded traffic. |
| At least two deployed application replicas | **UNVERIFIED.** Passing ASGI tests instantiate two independent production middleware instances, not deployed RC applications. No RC deployment ran in this round. |
| Sustained load exposing saturation, queue growth, lease reclaim, retries and leaks | **UNVERIFIED.** Sampler tests exercise real child memory/descriptors and missing measurements; this is not long-window application saturation/recovery evidence. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without execution. Passing admission-response tests cannot establish physical-effect uniqueness or Goal reconciliation. |
| Rate/security/degraded non-bypass under replica selection | **UNVERIFIED overall; independent allowances demonstrated.** Freshly passed `tests/test_soak_promotion_gates.py:439` observes `[200,200,429]` on each replica for the same identity, for both authenticated and unauthenticated cases. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:93` constructs its instance-local limiter. Six-path 429 probes prove local enforcement, not a shared principal allowance. |
| Required telemetry and explicit thresholds | **UNVERIFIED at RC level.** Documented thresholds are not newly observed series. `scripts/soak/run_soak.py:1410` samples driver-loop lag, not application event-loop latency. No new RC pool/lock/worker/queue/error series exists. |
| Kill/restart during active work proving drain/fencing/recovery | **UNVERIFIED.** Boot cleanup and promotion-gate tests pass; no active-work kill/recovery experiment ran. Process rejoin alone does not prove physical-work recovery. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** Lane designates source heads, not an immutable image/configuration to promote. `scripts/soak/run_soak.py:730` unconditionally returns a failed exact-artifact check. Fresh CLI regression tests confirm even four-hour synthetic preflight evidence cannot pass. |
| Findings filed/reclassified before promotion | Local findings recorded here. External filing/reclassification **UNVERIFIED**; remote mutations prohibited. Historical schema failure does not reproduce and current vulture scan passes. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED.** This report plus fresh validation logs are source-validation evidence, not an immutable deployed-RC soak bundle. |

## Architecture reconciliation and disposition

Read repository instructions, accepted ADR-085 and ADR-082526-b36a. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`, the canonical principal resolver,
and executor/store lease renewal, reclaim and fencing authority. Local request
budget enforcement is explicitly documented by production middleware; it cannot
be relabeled as the issue's stronger replica-selection non-bypass proof. No new
authorization path, limiter, scheduler, Goal store or execution authority was
introduced to force the soak acceptance to pass. The lease ADR requires actual
liveness/fenced recovery, not admission or restart counts as substitutes.

**BLOCKED:** the prior blocker is confirmed, not repaired by passing CI checks.
Only this report changed. No speculative scanner fixes, ledger changes, gate
weakening, merge, background workload, or remote mutations were performed.
No Docker-availability limitation is asserted.

Next required input/work: designate the immutable RC image and runtime config;
resolve the replica-budget acceptance contract; complete representative workloads,
physical-effect/recovery oracles and application telemetry; run that unchanged
deployed RC for the profile's minimum 14400 seconds and publish hash-bound results.
Repeating the stale schema/vulture repair or extending the host-process emulator
cannot satisfy this prerequisite.

Checkpoint: checked 1 issue; acceptance-complete 0; skipped issues 0;
validation-command errors 0; 6 explicitly reported live-PG test skips. Commit this
report locally as a blocked writer handoff, not integration approval.
