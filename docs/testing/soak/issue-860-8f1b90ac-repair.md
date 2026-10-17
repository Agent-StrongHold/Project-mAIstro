# Issue #860 — repair checkpoint (8f1b90ac)

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`03de29df6ec133ee1b305c3162c9b30577d9cb7c`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Initial worktree clean; no salvage required. No GitHub mutations.

Repair targets: reproduce the requested exact vulture gate, inspect its actual
findings before any ledger change, and validate existing soak acceptance probes.
Candidate edit files are `quality/vulture-baseline.json` only if the exact scan
requires reviewed changes, and this report. Existing source/tests are inspection
and validation inputs, not authorization for unrelated repairs.

The supplied job directory contains no `check-*.log` files. The previous result
reports BLOCKED; its claims are not treated as fresh validation. Ambiguity:
no exact release-candidate designation is present in the lane brief. Proceed
with local validation, never label it production or exact-RC soak evidence.

## Recorded validation checkpoint

- Exact requested vulture scan PASSED: 1322 findings, 1322 reviewed identities,
  zero unclassified. No ledger amendment is justified by actual evidence.
- Read historical `98a113.../check-3.log`: schema fence test expected 21 DDL
  statements but observed 24. Fresh `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` PASSED:
  37 passed, 6 skipped. Historical failure is not reproduced.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.

Read the issue acceptance body from the supplied dispatch snapshot and accepted
ADRs 081426-1f7c, 081626-f383, 082526-b36a. The lease renewal/reclaim ADR extends
the original fence contract; process restart alone is not authority to reclaim
another live task worker. Preserve Goal → Graph → Run → NodeRun → Attempt.
No architecture change or substitute authority is warranted.

## Focused acceptance validation

Executed with 600–1200 second command timeouts:

```text
uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q
93 passed in 2.63s

uv run python scripts/check-backlog-consistency.py
PASS: 168 backlog items
```

The earlier schema command produced 37 passed, 6 skipped in 1.36s. Skips are
not deployed PostgreSQL concurrency evidence. No source or test changes were
needed; no test inventory delta is introduced. Only this report changed.

### Reachable behavior inspected

- `main.py:648` installs production `RateLimitMiddleware`; its constructor in
  `api/rate_limit.py:94` creates an in-memory limiter per instance. The module
  explicitly documents N-times aggregate allowance at lines 32–37. Executed
  `tests/test_soak_promotion_gates.py:439` proves the same identity gets
  `[200, 200, 429]` independently from each instance, authenticated and anonymous.
  These are middleware ASGI probes, not deployed ingress tests.
- `main.py:735,755` mounts the task router. `api/tasks.py:144` reads the queue
  for a receipt. Executed `tests/test_soak_promotion_gates.py:564` uses the
  production router and a shared canonical admission spine: admitting instance
  returns 200, peer returns 404. No alternative admission authority is added.
- `scripts/soak/run_soak.py:744–755` unconditionally rejects exact-RC equivalence
  for host-process preflight. The passing promotion-gate suite checks that a
  longer run cannot override this gate.
- The schema test now independently expects the three validation audit columns
  at `packages/maistro-core/tests/persistence/test_pg_learnings.py:172–174`.
  This accounts for the historical 21-versus-24 failure without weakening tests.

### Acceptance matrix (all ten issue criteria)

| Criterion | Fresh evidence and remaining gap |
|---|---|
| Representative RC workload | UNVERIFIED. Reviewed `m3a-load-profile.md`; its one-key preflight explicitly lacks concurrent Workspaces, Graph fan-out, successful tools/models, Design/Canvas and sustained Goal workloads. No selected RC applicability decision. |
| At least two deployed application replicas | UNVERIFIED. Local ASGI probes exercise two instances, not the production deployment. |
| Sustained saturation, queues, reclaim, backoff, memory/descriptor/process leaks | UNVERIFIED. No sustained RC experiment or resource series executed. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal | UNVERIFIED. Fencing and recovery regression tests pass; they do not prove physical-effect uniqueness under production load. |
| Replica-resistant rate/security/degraded behavior | UNVERIFIED overall. Fresh probes demonstrate independent allowances and peer receipt loss. Backpressure tests pass, but no deployed ingress enforcement proof. |
| Production telemetry with explicit thresholds | UNVERIFIED. Profile defines thresholds but this round has no production observations. Driver-loop latency is not application-loop latency. |
| Active-work kill/restart, graceful drain/fencing/recovery | UNVERIFIED. Regression tests pass; no deployed process interruption performed. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. No immutable RC image/effective configuration designated; current runner fails exact-artifact gate by design. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog consistency passes; no new load or classification audit. No GitHub mutations. |
| Machine/human evidence bound to exact hashes | UNVERIFIED. This report binds local checks to the starting source commit, not production image/package/configuration hashes. |

## Handoff

**BLOCKED** on release acceptance, not on a reproduced CI failure. The specified
vulture command has no unbanked identities; amending a passing ledger would be
unsupported. No merge conflict exists, so the conditional develop-sync repair
was not invoked. No remote calls or mutations were performed.

Next required inputs: designated immutable RC artifacts and effective deployment
configuration, representative-workload applicability decisions, and a production
soak that observes physical effects/fences, active-work interruption, telemetry,
and hash-bound results. Resolve or explicitly reconcile the replica budget and
receipt limitations before claiming acceptance. Do not dispatch the stale schema
failure as an unresolved deterministic repair without fresh failing evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues; errors 0
validation commands. This documentation commit preserves fresh results and the
unresolved acceptance boundary; it is not integration approval.
