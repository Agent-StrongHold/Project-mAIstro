# Issue #860 — bounded repair f7280cdf

## Frozen scope and initial evidence

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting head: `89173a492bb2c4f1aae662f03b8f1c1d77924233`; supplied base:
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
- Edit snapshot: this report; `quality/vulture-baseline.json` only if the
  requested exact scan identifies reviewed debt requiring repair. No other
  issue, remote enumeration, or production authority changes.
- Current job directory has no driver `check-*.log` files. Read the supplied
  historical `98a113.../check-3.log`: schema fence expected 21 statements,
  observed 24. Reproduction is pending, not assumed fixed.
- Executed exact requested vulture scan: PASS, 1322 findings / 1322 reviewed
  identities, zero unclassified. No evidence justifies a ledger amendment.
- Ambiguity: dispatch specifies no immutable RC artifact/effective deployment
  configuration. Use local checks only; do not substitute the host-process
  preflight for an exact-RC soak. Previous BLOCKED result is historical evidence,
  not a fresh validation result.

## Validation checkpoint

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped. Historical failure not reproduced. The current
  independent DDL expectation includes the three validation audit columns at
  `test_pg_learnings.py:172–174`; no test weakening needed. Skips are not live
  PostgreSQL concurrency evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.
- Read accepted ADRs 081426-1f7c, 081626-f383 and 082526-b36a. The latter
  extends fencing with renewal/reclaim; restarting one worker is not permission
  to reclaim another live worker. Preserve Goal → Graph → Run → NodeRun → Attempt.
  No architecture reconciliation or new execution authority is needed.

## Focused production-seam validation

Executed (1200-second timeout):

```text
uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q
93 passed in 2.63s

uv run python scripts/check-backlog-consistency.py
PASS: 168 backlog items
```

Reachability inspection confirms `main.py:648` installs `RateLimitMiddleware`,
whose constructor (`api/rate_limit.py:93`) creates an in-memory limiter per
instance. The executed test at `tests/test_soak_promotion_gates.py:439` observes
`[200, 200, 429]` independently on each instance for the same anonymous or
credentialed identity. This proves local enforcement, not a shared budget.
The module documents N-times aggregate allowance at lines 32–37.

`main.py:735,755` mounts the production task router; `api/tasks.py:144` reads
its local queue. The executed receipt probe at
`tests/test_soak_promotion_gates.py:564` uses that router and a shared canonical
admission spine: the admitting instance returns 200, its peer returns 404.
These are ASGI probes, not deployed ingress experiments.

`scripts/soak/run_soak.py:744–755` explicitly returns `ok: False` for exact-RC
artifact equivalence. Passing promotion-gate tests verify that longer duration
cannot override this limitation. No speculative scanner repair is justified.

## Acceptance matrix

| Issue criterion | Executed evidence / remaining boundary |
|---|---|
| Representative RC profile | UNVERIFIED. Read `m3a-load-profile.md`; it explicitly lacks concurrent Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal workloads. Selected-RC applicability is not supplied. |
| At least two deployed replicas | UNVERIFIED. Two local ASGI instances were exercised, not two deployed application replicas. |
| Sustained saturation, queues, lease reclaim, backoff and leaks | UNVERIFIED. Regression tests pass; no sustained RC load/resource series executed. |
| No duplicate physical work across canonical operations | UNVERIFIED. Fencing and recovery tests pass, but are not production-load physical-effect evidence. |
| Replica-resistant security/rate/degraded behavior | UNVERIFIED overall. Independent allowances and peer receipt loss are reproduced; backpressure tests pass. No deployed ingress proof reconciles these limitations. |
| Production telemetry and explicit thresholds | UNVERIFIED. Profile defines thresholds; no production measurements collected in this round. Driver-loop latency cannot stand in for application-loop latency. |
| Active-work restart/drain/fencing/recovery | UNVERIFIED. Recovery regressions pass; no deployed active-work kill/restart performed. |
| Long exact-RC soak | UNVERIFIED. Immutable artifact/effective configuration not designated. Current preflight rejects equivalence by construction. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog consistency passes; no new load/classification audit or GitHub mutation. |
| Machine/human evidence bound to exact hashes | UNVERIFIED. This handoff binds local validation to starting source HEAD, not production image/package/configuration hashes. |

## Final disposition and next required input

BLOCKED on issue acceptance, not on a reproduced deterministic gate failure.
The requested scan passes, so no ledger edit is warranted. The historical schema
failure is stale at the assigned HEAD. No merge conflict exists; the conditional
develop-sync repair does not apply. No source/test changes or inventory delta.
Only this report changed, to be committed locally; no remote mutations.

Required next: designate immutable RC artifacts, effective deployment configuration
and workload applicability; supply/run a promotion-capable production soak with
physical-effect observations, active-work interruption, application telemetry,
and hash-bound evidence. Resolve or reconcile replica allowance and receipt
limitations before claiming acceptance. Repeating local checks cannot remove
that release-evidence dependency.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues; errors 0
validation commands. This report is a handoff, not integration approval.
