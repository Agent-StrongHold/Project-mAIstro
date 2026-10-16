# Issue #860 — bounded repair checkpoint (9ec969b5)

## Frozen scope

- Only issue #860, starting at `b1894bcd059c9588edc4e824f8059c9d8ba9e13e`,
  supplied base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Inspect existing soak runner/tests/profile, relevant ADRs and supplied prior
  failure. Execute the requested exact vulture scan and focused validation.
- Candidate edit surfaces: this report, `quality/vulture-baseline.json` only
  for observed reviewed identities, and soak runner/tests/inventory note only
  if a reproducible defect warrants repair. No other issues or PRs processed.
- Initial worktree clean; assigned HEAD verified. No incoming work to salvage.
- Current job directory contained no `check-*.log` files at initial inspection.
- Ambiguity: exact RC artifact/configuration is not supplied in the lane brief.
  Do not treat local ASGI probes or prior reports as production soak proof.

## Progress

- Exact CI vulture scan passed: 1322 reviewed identities / 1322 findings,
  zero unclassified or prohibited identities. No ledger amendment is warranted.
- Prior `98a11313/check-3.log` failed the schema-fence test (24 statements vs
  21 expected). Current test explicitly includes the three validation audit
  columns; rerunning the affected suites passes. The cited failure is stale.
- Focused validation: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
  returned **118 passed, 6 skipped**. This includes real middleware probes of
  independent replica allowances and a real task-router peer receipt 404,
  plus fail-closed exact-artifact CLI tests. It is not a deployed soak.
- No reproducible scanner or focused test failure warrants source/test edits.
  No tests were added; no suite-inventory delta is required.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: passed.
- `uv run python scripts/check-compose-secrets.py`: passed, 9 tracked files.
- `uv run python scripts/check-merge-markers.py`: passed.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites / 31323
  unique test identities, zero duplicate evidence. This is inventory, not a
  claim that the full test suite executed.
- Attempted documentation paths `docs/testing/soak/README.md` and
  `docs/adr/ADR-081-deployment-topology.md`: not found; skipped. Actual load
  profile and production Compose file were read instead.

## Architecture reconciliation

Read repository instructions, the documentation authority map, accepted
ADR-081426-1f7c (runtime mechanics), ADR-081626-f383 (Attempt execution leases)
and ADR-085 (principal rate limits). Preserve `Goal -> Graph -> Run -> NodeRun
-> Attempt`; no new execution, scheduling, event, or authorization authority.
The fencing ADR explicitly does not define expiry-driven takeover: the issue's
reclaim criterion cannot be satisfied by inventing timeout takeover in the load
driver. Admission deduplication is not proof of unique physical execution.
ADR-085 principal identity likewise does not prove a shared cross-replica budget;
the actual middleware documents independent per-process limits.

## Acceptance audit (all promotion criteria remain UNVERIFIED)

| # | Criterion | Current evidence and remaining gap |
|---|---|---|
| 1 | Representative RC load profile | `m3a-load-profile.md` defines a preflight and thresholds but explicitly lacks multi-user/Workspace traffic, Graph fan-out, successful model/tool calls, Design/Canvas and background reconciliation. RC-specific applicability unresolved. |
| 2 | At least two deployed application replicas | `deploy/docker-compose.prod.yml` declares two replicas; executed tests use ASGI instances, not deployed replicas. No live deployment was run in this attempt. |
| 3 | Sustained saturation, queue growth, reclaim, retries and leaks | Focused tests validate accounting and sampling only; no long-running workload executed. |
| 4 | No duplicate physical work across replicas | Admission tests pass but do not execute a production schedule/Attempt recovery workload. Canonical lease contract is not itself live evidence. |
| 5 | Replica-selection-resistant security/rate/degraded behavior | `tests/test_soak_promotion_gates.py:439` reproduces `[200,200,429]` separately on both limiter instances for the same identity; switching replica still yields allowance. `rate_limit.py:32` explicitly documents this scope. Six-path local enforcement is not a cluster budget. |
| 6 | Full telemetry and explicit thresholds | Profile contains thresholds, but no application-loop latency or complete worker/pool/reclaim observations from an exact-RC run. Sampler tests are not that evidence. |
| 7 | Active-work kill/restart, drain and fencing/recovery | No live active-work interruption executed. `tests/test_soak_promotion_gates.py:569` also reproduces a peer receipt 404 through the production router (`tasks.py:144` reads the local queue). This is visibility evidence, not proof of physical loss. |
| 8 | Long soak of exact RC artifact/config | `scripts/soak/run_soak.py:744` returns `ok=False` for exact artifact equivalence. Tests confirm even synthetic four-hour preflight evidence exits 1. Immutable RC image/config and a promotion-capable runner remain unresolved. |
| 9 | Findings classified to earliest broken invariant | Historical evidence pack exists, but classification completeness is not established by these checks. No GitHub mutations performed. |
| 10 | Machine/human evidence tied to exact hashes | Historical preflight evidence is explicitly provisional. This report is local validation, not a new hash-bound production soak pack. |

## Disposition / handoff

**BLOCKED**, not integration approval. The requested CI repair has no remaining
reproduced failure: exact-debt ledger and the cited schema-fence test both pass.
Do not alter a passing ledger or weaken evidence gates to force a change.
Only this report changed; no source, tests, grants, or ledgers changed.

To resume acceptance work, provide/select the immutable RC image and normalized
production configuration (including reachable gateway and supported workload
scope), supply an exact-topology runner, and execute the >=4-hour workload with
physical Attempt/fencing observations and active-work failure injection. Resolve
or explicitly govern independent rate allowances and receipt visibility before
claiming replica-selection/recovery guarantees. No shorter preflight can replace
that evidence. Full package suites and production/PostgreSQL soak validation were
not executed; the six skipped tests are not counted as proof.

Checkpoint: checked 1 assigned issue; done 0 acceptance-complete issues; skipped
0 assigned issues; reproduced CI errors 0; next: exact-RC prerequisites and soak.
