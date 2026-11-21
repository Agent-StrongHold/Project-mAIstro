# Issue #860 — repair checkpoint (6a575c08)

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD `c14815cfcef0f8cf5e6dad19b7bac5dd461f195e`; supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`. HEAD matches; worktree was clean.
- Inputs: supplied dispatch snapshot, previous `adb208a5` result and historical
  `98a11313/check-3.log`. No current-job check logs were present at initial snapshot.
- Inspect: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `packages/maistro-core/{src/maistro/persistence/pg_learnings.py,tests/persistence/test_pg_learnings.py}`,
  production rate middleware, relevant ADRs and CI gate definitions.
- Allowed repair surfaces: the schema test/implementation if failure reproduces,
  reviewed vulture ledger identities if the required scan reports drift, this
  handoff, and an inventory note only if tests change. No speculative code repair.

## Initial evidence and assumptions

Historical check-3 failed because the schema test expected 21 statements but saw
24. The previous result reports that this no longer reproduces; revalidation is
required. The previous result also reports no exact-RC soak evidence. Treat the
assignment as a writer CI-repair round, not authorization to certify an unspecified
release artifact or alter execution/authorization architecture.

## Fresh validation checkpoint

- Required exact Vulture invocation passed: 1323 findings / 1323 reviewed
  identities, zero unclassified or forbidden; selected base `4aa68edc0b6b`.
  No ledger amendment is justified by the actual scan.
- `uv sync --locked --extra dev`: passed (214 installed packages checked).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`:
  **103 passed, 6 skipped in 2.66s**. PostgreSQL cases explicitly skipped because
  `MAISTRO_TEST_PG_DSN` is unset; these are not live database validation.
- Historical check-3 failure does not reproduce. Current schema expectations
  explicitly include all three validation-audit columns (24 operations total).
- Read the ten acceptance criteria from the frozen issue body. Full production
  soak acceptance remains distinct from the passing regression suite.

## Additional executed validation

Commands used 1200–1800 second timeouts. Output is in this job's session trace.

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files |
| `uv run python scripts/check-suite-inventory.py` | PASS; 17 suites, 31128 unique test identities, zero duplicate evidence |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence only, not deployment operation |
| `git diff --check` | PASS |

The required scan was `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, matching
`.github/workflows/quality.yml:1078–1081`. Its automatically selected base is
recorded above; no explicit dispatch-base override was used.

## Architecture and reachable behavior

Read repository instructions, documentation authority map and accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085. No architecture
change is made: preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`, durable
Attempt fencing, and renewal/expiry-based reclamation rather than assuming a
restart proves another worker dead. Admission uniqueness does not prove physical
work uniqueness. ADR-085 specifies principal keying, not evidence that the
current middleware shares a cluster-wide allowance; it does not waive the
issue's replica-selection criterion.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`
  takes the schema advisory lock inside the transaction. The independently
  listed test expectations at `tests/persistence/test_pg_learnings.py:162–194`
  (within that package) include the validation-audit upgrades absent from the
  historical failed test. Fresh tests pass without modifying expectations.
- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` creates an instance-local
  `InMemoryRateLimiter`. Executed
  `tests/test_soak_promotion_gates.py:439–489` verifies both authenticated and
  unauthenticated identities get `[200, 200, 429]` independently on each replica.
  This is a real middleware contract discrepancy with cluster non-bypass, not
  evidence of a deployed full-stack exploit or shared-budget enforcement.
- `scripts/soak/run_soak.py:730–741` always fails `exact_rc_artifact` because
  it launches host processes, not the promoted image/configuration. Existing
  promotion-gate/CLI tests executed in the targeted command preserve this guard.
- `docs/testing/soak/m3a-load-profile.md:151–170` explicitly identifies missing
  representative workload, application-loop, pool-saturation and long-window
  evidence. Lines 193–203 distinguish the schedule admission race from physical
  execution: its queued probe Run is cancelled without executing.

## All ten acceptance criteria

| Criterion | Current executed evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: existing profile explicitly lacks concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and background reconciliation applicability. No designated RC profile supplied. |
| At least two deployed application replicas | **UNVERIFIED**: two ASGI middleware instances ran in regression tests, not a deployed RC pair. |
| Sustained saturation, queue growth, reclaim/retry and leak observation | **UNVERIFIED**: 2.66-second regression execution is not sustained-load evidence; no new soak or telemetry series ran. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED**: admission and gate regression checks cannot establish physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**: executed production middleware tests reproduce independent allowances on both replicas. Broader deployed concurrency/security behavior remains **UNVERIFIED**. |
| Complete PostgreSQL/application-loop/worker/RSS/descriptor/queue/error telemetry and thresholds | **UNVERIFIED for RC**: profile and sampler tests exist, but no complete measured RC series was produced. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**: no active-work fault injection or physical recovery witness ran. Boot/gate regressions do not substitute. |
| Long soak of exact promoted RC/configuration, repeated after changes | **UNVERIFIED / BLOCKED**: supplied source head is not a designated immutable promotion image/configuration; host-process driver deliberately cannot certify it. |
| Findings filed/reclassified before promotion | Local findings/disposition recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations are prohibited. Rate allowance discrepancy is a correctness prerequisite, not throughput optimization. |
| Machine/human evidence tied to exact artifact/configuration hashes | **UNVERIFIED for RC**: this source-bound validation record is not a promotion evidence bundle; historical bundles are not recertified. |

## Disposition and required next step

**BLOCKED** on production acceptance evidence; no current Vulture drift or schema
regression found to repair. Only this report changed. No code, tests, gates,
ledgers or grants changed; no test inventory delta is required. Previous work is
preserved. The inherited broad branch diff is not integration-certified by this
bounded check. This was not a develop-sync conflict, so no fetch/merge was made.

Release owner must designate the immutable RC image and runtime configuration,
resolve the replica-budget contract discrepancy through the existing enforcement
path, complete representative production workloads and physical-work/telemetry
witnesses, then execute the long soak and publish its hash-bound evidence.
Repeating the same already-passing CI repair cannot establish those prerequisites.
Do not requeue this as a schema/vulture repair without new failure evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate RC and resolve production-soak prerequisites"}`.
Local commit is a handoff checkpoint, not promotion or integration approval.
