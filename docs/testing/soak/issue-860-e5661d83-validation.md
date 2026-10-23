# Issue #860 repair checkpoint — e5661d83

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`edfa83e5156b924e7871281fb504087009f24845`, supplied develop base
`4c1e9393624246e676994692bb1efc0e1bc94207`.
Initial worktree clean. No salvage necessary. No GitHub mutations.

Planned writes: this validation handoff; `quality/vulture-baseline.json`
only if the requested exact scan identifies reviewed retained debt.
Read-only inspection: supplied dispatch/prior result/check logs, repository
instructions, relevant architecture ADRs, soak runner/promotion tests and their
production dependencies, CI gate scripts/configuration.
No other issue or PR will be processed.

The supplied prior result is BLOCKED; its claims are not yet independently
validated. Current job directory contained no `check-*.log` at initial snapshot.
The referenced prior failure log will be inspected separately.

Ambiguity: the assignment is a CI repair of an operational soak issue. A clean
static gate is not equivalent to an executed exact-RC production soak. Neither
will be reported as the other.

## Results

- Mandated exact vulture scan passed: 1,322 findings, 1,322 reviewed
  identities, zero unclassified/never-allowlist. No ledger repair justified.
  The script selected ratchet base `321cbdb8fe9b`; supplied develop base also
  resolves locally. Neither ref was changed.
- Historical `98a113.../check-3.log` reports an ordered schema-DDL test mismatch:
  24 actual statements versus 21 expected. Fresh execution passes: the current
  independent ordered oracle explicitly includes all three validation audit
  columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:172`.
- Read repository instructions and complete issue acceptance body from the
  frozen dispatch; no remote enumeration performed.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  **136 passed, 6 skipped**, 2.60s. Skips do not establish live database safety.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.

Read accepted ADR-081226-a66b (one execution hierarchy), ADR-081626-f383
(Attempt lease fencing), and ADR-073126-c4e1 (exact release artifacts).
Reconciliation: the lease ADR explicitly does not define expiry takeover;
this issue cannot authorize a competing reclaim mechanism. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. A local host-process preflight
cannot be substituted for the immutable RC artifact.

Production-path regression evidence inspected after execution:

- `tests/test_soak_promotion_gates.py:439`: actual middleware instances allow
  `[200, 200, 429]` on each replica for the same identity, authenticated and
  unauthenticated. Exhausting one replica does not exhaust its peer.
  `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` allocates
  process-local limiter state; `maistro_server/main.py:648` installs it in the
  production application. This agrees with the documented #842 contract,
  but does not prove a replica-independent shared budget for #860.
- `tests/test_soak_promotion_gates.py:564`: actual task router with two queues
  and one canonical admission spine returns owner 200 / peer 404 for the same
  admitted receipt. The HTTP handler reads its local queue (`api/tasks.py:144`).
  This is a real seam failure, not evidence of deployed recovery.
- `scripts/soak/run_soak.py:744`: preflight artifact check always fails.
  CLI regressions reject synthetic four-hour results with missing, null or
  preflight artifact identity. These are negative gate tests, not a live soak.
- The existing load profile explicitly documents missing concurrent
  users/Workspaces, Graph fan-out, successful tool/model operations,
  Design/Canvas, sustained Goal reconciliation and application-loop telemetry.
  No change to this report can supply those operational observations.
- `pg_learnings.py:215` encloses schema upgrades in the transaction before
  acquiring the advisory lock; the passing fake-connection oracle verifies
  statement ordering, not a live concurrent PostgreSQL boot.
- The runner publishes the failing artifact check at `run_soak.py:1579` and
  uses `failed_promotion_checks` for CLI exit at line 1760. The rejection is
  reachable behavior, not merely an unused helper.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED**: profile has documented workload gaps; no complete RC profile executed. |
| Two deployed application replicas | **UNVERIFIED**: ASGI instances are not deployed production replicas. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED**: sampler regressions passed, no sustained deployment run. Reclaim requires the accepted ADR reconciliation above. |
| No duplicate physical work | **UNVERIFIED**: admission-oracle tests are not physical Attempt execution proof. |
| Replica-resistant rate/security/degraded behavior | Shared allowance **not established**: executed tests reproduce independent budgets. Remaining deployed security behavior **UNVERIFIED**. |
| Complete production telemetry and thresholds | **UNVERIFIED**: sampler tests pass but do not measure a production application's event loop or long-window resource health. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED**: no active production replica restarted; receipt visibility regression demonstrates a gap, not recovery. |
| Long exact-RC soak | **UNVERIFIED / BLOCKED**: no immutable promotable artifact/config supplied; existing runner fails exact-artifact equivalence by design. |
| Findings filed/reclassified | **UNVERIFIED** for completeness/external filing; local findings recorded without prohibited GitHub mutations. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED** for RC soak; this starting-head-bound validation report is not an artifact-bound production observation. |

## Final handoff

**BLOCKED**, not integration approval. The historical test failure is no longer
reproducible and the required vulture gate is clean. No actual evidence justifies
a source/test/ledger repair in this round. Only this report changed; no tests
were added, removed or renamed, so no inventory delta is required. Existing
work and historical evidence were preserved. No merge conflict was present.

Next: supply the immutable RC artifact and supported runtime configuration,
resolve the replica-budget contract and workload/recovery gaps, then execute
an exact-artifact soak with physical-work oracles and application telemetry.
Do not retry identical static validation as a substitute for these prerequisites.
Do not invent reclaim authority or relax the promotion gate.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; validation command
errors 0. Local commit contains a blocked handoff only.
