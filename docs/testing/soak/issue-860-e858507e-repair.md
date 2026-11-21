# Issue #860 — bounded repair e858507e

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `8f28f8125c4e77bbd22d9e8401d7b4a09d3d4f75`, supplied base
  `2154f845347c9541016288c760f8da3f5cd2e064`.
- Starting worktree clean; no uncommitted salvage needed.
- Inspect supplied dispatch snapshot and prior result/check-3.log, repository
  instructions, relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, load profile, evidence verifier,
  production rate limiter and adjacent tests, vulture checker and ledger.
- Potential edits limited to evidence-backed fixes in those files and required
  inventory notes; this report records validation and unresolved acceptance.
- No driver `check-*.log` files present in this job directory at initial listing.
  Assumption: reproduce the explicitly supplied prior failure rather than infer
  a current gate failure. No GitHub mutations or release approval.

## Progress

- Exact CI vulture scan passed: 1323 reviewed identities / 1323 findings,
  zero unclassified or never-allowlisted. No ledger change warranted.
- Supplied historical check-3.log reports 24 actual versus 21 expected learning
  schema DDL statements. Reproduction is pending; no assumed current failure.
- Load profile explicitly calls the driver a host-process preflight, excludes
  key representative workloads, and requires a >=4-hour exact-RC soak.
  Prior result's BLOCKED verdict is not itself acceptance evidence.
- Historical failure freshly NOT REPRODUCED:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed (37 passed, 6 skipped). Skips are not live PostgreSQL proof.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed
  (3277 files already formatted). Commands used 1200-second timeouts.
- No scanner or test repair justified by these results.

## Architecture and reachable behavior

Read accepted ADR-081226-a66b, ADR-081626-f383 and ADR-085. Preserve the
Goal -> Graph -> Run -> NodeRun -> Attempt model. The fencing ADR explicitly
excludes implicit expiry takeover: issue wording cannot authorize a competing
reclaimer. ADR-085's per-principal rate limits do not make a local limiter shared.

Fresh source inspection confirms `main.py:648` installs RateLimitMiddleware,
whose `api/rate_limit.py:93` creates an InMemoryRateLimiter. The existing
`test_soak_promotion_gates.py:439` tests identical credentials/IP on two middleware
instances and asserts separate allowances; executing that test is next.
`run_soak.py:744` always rejects the host-process artifact, and `:1067` cancels
probe Runs without executing physical work. These are real acceptance gaps, not
vulture findings. No replacement execution or authorization authority introduced.

## Completed validation

All commands used 1200-second timeouts; no failed validation commands.

- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  80 passed, including both authenticated/unauthenticated independent-replica
  allowance counterexamples and rejection of four-hour host-process preflight.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  27 passed. These are focused tests, not a deployed soak.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- Learning-schema test/source inspection confirms the three Gauntlet audit
  columns are already in the independent expected-DDL list (:177–179), and
  production `ensure_schema` executes upgrades inside the advisory-locked
  transaction (:215–223). Historical check-3.log needs no further repair.

## Acceptance audit

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | Profile inspected; it explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal workers. Complete criterion UNVERIFIED. |
| Two application replicas | Two ASGI middleware instances tested, not two deployed RC replicas. UNVERIFIED. |
| Sustained saturation, queues, reclaim, retry, leaks, shutdown | No sustained production soak executed. UNVERIFIED. |
| Physical-work uniqueness and Goal reconciliation | Admission probe cancels rather than executes its Run. Physical effects and reconciliation UNVERIFIED. |
| Rate/security/degraded behavior and replica non-bypass | Fresh tests reproduce [200,200,429] independently on each middleware instance for the same identity. Aggregate non-bypass NOT MET; full deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry with thresholds | Profile inspected; driver-loop lag is not application-loop lag, receipt reads are local. Complete production telemetry UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | No active-work deployed restart executed. UNVERIFIED. |
| Long exact-RC soak, rerun after change | Passing rejection test proves four-hour host preflight cannot certify RC. No exact-RC soak executed; UNVERIFIED. |
| Findings classified to earliest invariant | Backlog consistency passes, but complete load-derived classification UNVERIFIED. No GitHub changes. |
| Human/machine evidence bound to image/package/commit/config hashes | This is a local validation report, not production soak evidence. UNVERIFIED. |

## Disposition

**BLOCKED**: checked 1 issue, acceptance-complete 0, skipped 0, failed validation
commands 0, blocked 1. Only this report changed. No new tests, inventory delta,
code edits, or ledger amendments are warranted by fresh results. All inherited
work remains intact. Local commit required; no integration approval or closure.

Next: select the immutable RC/config and complete production workload, resolve
aggregate rate-policy behavior, obtain canonical physical-effect/recovery
observations, then run the >=4-hour exact-RC soak with hash-bound evidence.
Repeating the clean vulture scan or the already-fixed DDL test cannot resolve
these acceptance blockers. Do not relabel host preflight as production proof or
introduce lease takeover contrary to the accepted ADR.
