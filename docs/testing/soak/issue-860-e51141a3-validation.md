# Issue #860 — e51141a3 focused repair validation

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting head: `0a591a4ed5c920c7f19da7c505a44e63217b4228` (verified).
- Assigned base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Starting worktree: clean; no incoming edits to salvage.
- Process only the supplied dispatch snapshot, prior `check-3.log`, vulture
  gate, and #860 soak production paths/tests. No GitHub mutations or ref updates.
- Candidate edit scope: this report and `quality/vulture-baseline.json` only
  if the mandated scan demonstrates reviewed retained identities needing repair.
- Ambiguity: the prompt includes verifier and writer instructions; the explicit
  repair lane and mandatory commit identify this run as a writer.
- No `check-*.log` files were present in the assigned job directory at start.

## Progress

Starting head and clean state verified. Prior result reports BLOCKED; its claims
were not treated as fresh verification.

Fresh results:

- Mandated vulture command: PASS, 1,322 findings / 1,322 reviewed identities,
  zero unclassified and never-allowlist findings. No ledger amendment justified.
- Historical `98a113.../check-3.log`: schema oracle expected 21 statements but
  production emitted 24. Current test explicitly includes the three validation
  audit columns; fresh execution below does not reproduce that failure.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 110 passed / 6 skipped in 2.14 seconds. Skips are not live DB evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.

Read the frozen issue's complete acceptance body, the current load profile,
relevant production-path regression tests, and accepted ADR-081226-a66b,
ADR-081626-f383 and ADR-073126-c4e1. Reconciliation: lease-expiry takeover is
outside the accepted fencing contract; this lane cannot invent reclaim authority.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt model remains unchanged.
No exact promotable artifact/configuration is identified in the lane assignment;
a host-process preflight is not substituted for that identity.

Additional acceptance validation:

- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  PASS, 26 passed in 2.13 seconds.
- Production reachability: `maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` allocates a separate in-memory
  limiter per instance. The executed test at
  `tests/test_soak_promotion_gates.py:439` exhausts one identity on replica A,
  then obtains two more successful requests on B (both authentication modes).
  This implements the documented #842 per-process contract, not #860 proof of
  a shared allowance. No authorization or rate-budget redesign is attempted.
- `api/tasks.py:144` reads the local queue; the executed production-router test
  at `tests/test_soak_promotion_gates.py:564` observes owner 200 / peer 404.
- `pg_learnings.py:215` enters the transaction before taking the advisory lock;
  the independent ordered-DDL regression passes with all 24 statements.
- `scripts/soak/run_soak.py:744` always returns a failed exact-artifact check.
  Executed CLI regressions reject otherwise-passing synthetic four-hour
  evidence with missing, null or preflight artifact identity. This is safe
  rejection evidence, not an executed four-hour soak.

## Acceptance matrix

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**: current profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal reconciliation. |
| At least two deployed replicas | **UNVERIFIED**: separate ASGI instances in tests are not deployed production RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks | **UNVERIFIED**: sampler regression passed, but no sustained production workload was executed. Reclaim requires the ADR reconciliation above. |
| No duplicate physical work | **UNVERIFIED**: admission-oracle tests are not physical Attempt execution/fencing evidence. |
| Replica-resistant security/rate/degraded behavior | **UNMET** if a shared identity allowance is required: executed middleware tests reproduce independent budgets. Local rate-limit suite passes; complete deployed security remains **UNVERIFIED**. |
| Complete telemetry and explicit thresholds | **UNVERIFIED** at RC scope: process-group sampler tests pass, but driver-loop measurements cannot prove application-loop latency, saturation or long-window health. |
| Active-work kill/restart/drain/recovery | **UNVERIFIED**: no production replica was restarted; passing receipt test reproduces cross-replica visibility failure, not successful recovery. |
| Long soak of exact RC | **UNVERIFIED / BLOCKED**: no immutable promotable artifact/configuration supplied; existing host-process runner rejects equivalence. |
| Findings filed/reclassified | **UNVERIFIED** for completeness/external filing; local evidence recorded, no GitHub mutations permitted. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED**: this starting-head-bound validation report is not a hash-bound production soak. |

## Handoff

**BLOCKED.** No current CI failure justifies changing source, tests or the ledger.
Only this report changed. No tests added/removed/renamed, so no inventory delta
is required. Existing source, tests, inventory notes, ledgers and historical
artifacts are preserved. There was no develop-sync conflict to resolve.

Next action is not another identical CI retry: identify the immutable RC and
supported deployment configuration, settle the replica-budget contract and
representative workload/recovery gaps, then execute a >=4-hour exact-artifact
soak with application telemetry and physical-work oracles. Never manufacture
reclaim authority or waive the exact-artifact gate to obtain a green result.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation command errors 0. Historical failure not reproducible. This local
commit is a blocked handoff, not integration approval.
