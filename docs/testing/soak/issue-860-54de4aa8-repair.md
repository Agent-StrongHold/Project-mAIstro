# Issue #860 repair checkpoint — 54de4aa8

## Frozen scope

Only issue #860 at starting head `141ffb2b15569f61653475adf746d0831caaee1a`,
base `3c761d14db944a727fa0744444bc67cfe36d49f7`, and the supplied dispatch snapshot.
No remote mutations, ref refresh, or expansion to linked issues/PRs.
Worktree initially clean; no salvage required.

Planned file scope: this report; `scripts/soak/run_soak.py`, adjacent soak tests,
profile/evidence documentation, production middleware (inspection only), relevant
ADRs and CI scripts (inspection only), and `quality/vulture-baseline.json` only
if the explicitly requested scan identifies reviewed retained debt. Any test
change requires a matching inventory note. No scheduler or authorization changes.

## Initial evidence / ambiguity

- Current job directory contains no `check-*.log` files. Inspect the explicitly
  supplied previous `check-3.log` instead, then reproduce validation locally.
- Prior result reports BLOCKED, not completion. Its claims remain unverified.
- No exact promotable RC artifact/configuration is specified in the assignment;
  do not substitute a host preflight for production RC evidence.

## Progress

- Historical `check-3.log` fails the schema fence's old 21-statement assertion.
  Current expected DDL already includes the three Gauntlet audit columns.
- Re-executed `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** (28.28s). Historical failure not reproduced.
- Re-executed requested exact vulture scan: **PASS**, 1,323 reviewed identities,
  1,323 findings, zero unclassified/never-allowlist findings. No ledger edit
  justified. Default provenance base printed by gate: `4aa68edc0b6b`.
- No code/test repair is supported by either cited CI concern.
  Continue bounded acceptance inspection; no expansion to other issues.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3,270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **65 passed** (1.31s).
  Includes real production middleware instances proving independent allowances,
  and real child-process sampler coverage; neither is a deployed RC soak.
- `uv run python scripts/check-suite-inventory.py`: **PASS**, 17 suites,
  31,128 unique identities, no duplicated evidence. No tests added/changed;
  no inventory delta required. All validation commands used 1,200s timeouts.

## Architecture reconciliation

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082126-f69c, and
ADR-082526-b36a. The later lease ADR extends the earlier boundary with fenced
renewal/reclaim; schedules produce canonical Runs, not a second runtime.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt authority is unchanged.
Replica-local enforcement is documented in production middleware; changing that
policy/authority is not justified by a passing CI-ledger repair request.

## Acceptance audit (all ten criteria)

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**: `m3a-load-profile.md:152` explicitly lists missing multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas, and Goal/background traffic. No selected RC configuration justifies exclusions. |
| Two application replicas | **UNVERIFIED for RC**: executed middleware tests use two real middleware instances, not two deployed application images. |
| Sustained saturation, reclaim/retry, leaks | **UNVERIFIED**: imported current driver and evaluated `evidence/m3a-round30-shakedown.json`; actual sustain is 420.08s against 14,400s minimum. No new sustained deployment run performed. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED**: `scripts/soak/run_soak.py:1044` cancels the admission-probe Run without execution. Run admission uniqueness does not prove physical Attempt uniqueness or sustained Goal reconciliation. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; contrary rate evidence reproduced**: `tests/test_soak_promotion_gates.py:439` passes using production `RateLimitMiddleware`: same identity receives `[200,200,429]` independently on each instance. This matches process-local policy at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`, not a shared principal allowance. |
| Complete telemetry with thresholds | **UNVERIFIED**: profile has thresholds but acknowledges driver loop lag is not application event-loop latency and SELECT 1 wire time is not application query latency. No new RC telemetry. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**: 65 passing soak tests cover drain/cleanup gates, not a deployed active-work recovery with physical execution observations. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**: executed `preflight_artifact_check()` returns `ok=false`; current evaluator rejects historical evidence on exactly `sustain_duration` and `exact_rc_artifact`. No promotable immutable image/configuration designated. |
| Findings filed/reclassified | **UNVERIFIED externally**: local findings recorded here; GitHub mutations forbidden and not attempted. |
| Published machine/human exact-hash evidence | **UNVERIFIED for RC**: existing historical preflight JSON and this human validation report are not an exact-RC promotion pack. |

The artifact/evidence checks above ran via `uv run python` with assertions on
both failures and the false artifact result; command exited 0. `git diff --check`
also passed. Tests validate fail-closed reporting, not completion of the soak.

## Disposition and handoff

**BLOCKED.** Only this report changes. No code, tests, ledger, grant, gate, runtime
configuration or authority changed. The cited failure is already fixed and the
requested vulture scan passes; making an additional repair would be speculative.
No develop-sync conflict exists. No fetch/merge, remote mutation or destructive
command performed.

Next prerequisite: designate immutable RC image/configuration, complete the
representative production workload/telemetry and physical-work recovery probes,
reconcile the replica-selection rate-policy mismatch, then run the unchanged RC
for at least four hours and publish hash-bound evidence. Repeating this same
CI-repair dispatch cannot supply those prerequisites.

Residual risks: all production acceptance gaps above; six database-dependent
persistence tests skipped. No claim of real PostgreSQL validation in this round.
No test additions: no inventory note required. Report committed locally as the
mandatory writer checkpoint, not as integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`.
Here done means all acceptance satisfied, not CI checks passing.

