# Issue #860 repair checkpoint — 1c818205

## Frozen scope

- Sole item: issue #860, branch `auto-860`, starting head
  `b654ca88ab2f2ee5788761ac860b978e0db1b113`, supplied develop base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Read-only evidence: supplied dispatch context, previous result and cited failed
  check; repository instructions/ADRs; existing soak runner/profile, promotion
  tests, adjacent production rate/receipt paths and CI gate configuration.
- Write scope: this report; `quality/vulture-baseline.json` only if the required
  scan identifies reviewed retained identities (explicit CI-repair exception).
  No speculative production repairs, new execution authorities or gate changes.
- Initial worktree clean; no salvage needed. No GitHub mutations.
- Current job directory contains no `check-*.log`; inspect the explicitly cited
  prior check and independently execute validation instead.

## Ambiguity and assumption

The dispatch asks for CI repair but the prior result reports missing exact-RC
acceptance prerequisites. Treat these separately: reproduce the CI failure,
repair only demonstrated debt, and report production acceptance as unverified
unless current execution supplies evidence. Do not designate a release artifact
or silently substitute an in-process test for deployed multi-replica load.

## Results

- Required exact vulture scan: PASS; 1322 reviewed identities / 1322 findings,
  zero unclassified. No demonstrated debt warrants a ledger amendment.
- Cited prior `check-3.log` is a schema-fence test failure (24 DDL statements
  observed versus 21 expected), not a vulture failure.
- Fresh focused pytest run: PASS, 130 passed / 6 skipped in 2.64s. Paths:
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `tests/test_soak_promotion_gates.py`,
  `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`,
  `packages/maistro-core/tests/runs/test_execution_fencing.py`, and
  `packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py`.
  Executed with `uv run pytest <paths> -x -q` and a 1200-second timeout.
  The cited historical failure does not reproduce. Skips do not establish live
  PostgreSQL behavior. Logs: `/tmp/860-1c818205-{vulture,tests}.log`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 53 consumers;
  two non-fatal Python invalid-escape SyntaxWarnings were emitted.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `git diff --check`: PASS. All validation used 1200-second command timeouts.

## Architecture and reachable behavior

Read accepted ADR-081426-1f7c (Attempt identity / runtime mechanics),
ADR-081626-f383 (canonical store owns fencing), and ADR-082526-b36a
(renewal and expired-lease reclamation). The latter extends the former fencing
boundary; a restarting replica must not reclaim another live worker. Preserve
Goal → Graph → Run → NodeRun → Attempt; no reconciliation requires new authority.

Production `main.py:648` installs `RateLimitMiddleware`; its constructor at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates a
process-local limiter. Executed `tests/test_soak_promotion_gates.py:439`
observes `[200, 200, 429]` independently on both instances for the same identity.
This establishes local enforcement, not replica-independent aggregate allowance.
The production module explicitly documents N-times aggregate allowance.

Production `main.py:735,755` mounts the task router. Its receipt handler at
`packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the local
queue. Executed `tests/test_soak_promotion_gates.py:564` observes admitting
instance 200 and peer 404 using that router and a shared canonical admission
spine. These are in-process ASGI probes, not deployed ingress/load evidence.

`scripts/soak/run_soak.py:744` returns `exact_rc_artifact.ok=false` by design:
its host-process preflight is not the production Compose image/configuration.
Tests establish that duration cannot override this gate. The current profile
explicitly lists omitted representative workloads and telemetry limits.

## Acceptance audit

| # | Criterion | Current executed evidence / unresolved boundary |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED. Existing profile lacks concurrent Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal workloads; selected-RC applicability is not supplied. |
| 2 | Two deployed replicas | UNVERIFIED. ASGI instances were tested, not deployed application replicas. |
| 3 | Sustained saturation, queues, reclaim, backoff, leaks | UNVERIFIED. No sustained RC resource series collected; passing regressions are not load evidence. |
| 4 | No duplicate physical work | UNVERIFIED. Canonical fencing/recovery regressions pass; no production-load physical-effect observations. |
| 5 | Replica-resistant security/degraded behavior | UNVERIFIED overall. Local rate enforcement/backpressure pass; independent replica allowances and peer receipt 404 are reproduced. |
| 6 | Production telemetry with thresholds | UNVERIFIED. Profile thresholds exist; no production measurements collected. Driver-loop latency cannot substitute for application-loop latency. |
| 7 | Active-work kill/restart/drain/recovery | UNVERIFIED. Recovery regressions pass; no deployed active-work interruption performed. |
| 8 | Long exact-RC soak | UNVERIFIED. Immutable RC artifact/effective configuration not designated; current runner explicitly rejects equivalence. |
| 9 | Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog consistency passes, but no new load/classification audit or remote mutations. |
| 10 | Machine/human hash-bound soak evidence | UNVERIFIED. This report binds local checks to source HEAD, not exact production image/package/configuration hashes. |

## Disposition and handoff

BLOCKED on release acceptance. No deterministic failure reproduced, no scanner
findings guessed, no ledger changes warranted. No merge conflict exists.
Only this report changed; no tests added or changed, so no inventory delta.
The historical DDL expectation now includes all three validation audit columns
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:177–179`).

Next required input/work: designate immutable RC artifacts and effective runtime
configuration; justify workload applicability; execute a promotion-capable
production soak with physical-effect observations, application telemetry and
active-work interruption, then publish hash-bound results. Resolve or explicitly
reconcile the replica allowance/receipt limitations. Repeating local regressions
cannot satisfy those prerequisites. No release, integration or closure approval.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
errors 0 validation commands. Commit this report locally; leave the tree clean.

