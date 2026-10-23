# Issue #860 — repair checkpoint (46ab43aa)

## Frozen scope

- Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `1c4c1deae79e01cb875d6fd2fdc1a251a6b86fd8`.
- Assigned develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean; no incoming uncommitted work to salvage.
- Process the supplied dispatch snapshot, not live GitHub enumeration.
- Inspect issue body, relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, production rate limiting and adjacent
  tests, `scripts/check-vulture-baseline.py`, and the prior referenced log/report.
- Candidate edits limited to evidence-backed vulture fixes/ledger amendments,
  corresponding tests/inventory notes if needed, and this report.

## Initial observations

Current job directory contains no `check-*.log` files. Previous result says
BLOCKED; that is a claim to verify, not promotion evidence. The large inherited
diff is preserved, not treated as a request to repair unrelated issues.
Assumption: this is the writer CI-repair lane; missing exact release-candidate
identity cannot be replaced with a locally invented release designation.

## Reproduced validation

- Required exact vulture scan passed: 1323 findings / 1323 reviewed identities,
  zero unclassified. No ledger amendment is justified.
- Read supplied historical `98a113.../check-3.log`: failure was schema-body
  length 24 versus 21, not a vulture failure.
- Fresh focused pytest (learnings schema, soak promotion gates, stack boot,
  task concurrency backpressure): **111 passed, 6 skipped in 2.55s**.
  Skips require `MAISTRO_TEST_PG_DSN`; no database/RC evidence inferred.
- Complete issue body extracted from the frozen dispatch snapshot: ten
  acceptance criteria, including an unchanged exact-RC soak and physical-work
  fencing. Source inspection and acceptance audit are recorded below.

## Architecture and reconciliation

Read repository instructions and accepted ADR-073126-c4e1 (release artifact
provenance), ADR-082526-b36a (lease renewal/reclamation), and ADR-085
(principal rate limiting). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
A local build is not automatically the designated RC. Process rejoin and
admission deduplication are not physical-work fencing. The documented local
rate budget is narrower than #860's replica-selection non-bypass requirement;
that discrepancy is not an acceptance waiver. No alternate execution or
security authority was introduced.

## Commands executed

All validation commands used 1200-second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1323 reviewed identities / findings; zero unclassified. No ledger edit.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
  — PASS, 111 passed / 6 PostgreSQL-dependent skips in 2.55s.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py` — PASS, 17 suites,
  31128 unique identities, zero duplicate evidence.
- `uv run python scripts/check-deployment-claims.py` — PASS; component
  existence only, not deployed concurrency evidence.

## Acceptance audit

| Issue criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Inspected `scripts/soak/run_soak.py:1373–1395`: one credential and health/task/receipt/metrics mix. `docs/testing/soak/m3a-load-profile.md:152` explicitly lists absent concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker traffic. No designated RC applicability decision supplied. |
| At least two deployed replicas | **UNVERIFIED.** Executed tests route to independent production middleware instances, not deployed RC applications. No deployed soak performed this round. |
| Sustained saturation, queue growth, reclaim, retry and leaks | **UNVERIFIED.** Executed sampler regression observes real uv child memory/fd growth; it is not a sustained saturation/reclamation/leak test. Six database tests skipped, not counted as proof. |
| No duplicate physical work | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1068` cancels the unexecuted schedule-probe Run through the canonical store. Admission-probe tests do not establish Attempt fencing, physical effect uniqueness or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439`: the same identity gets 200,200,429 independently from both instances. Production `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs an in-memory limiter per instance. Backpressure tests prove retryable task 429 behavior only. |
| Required telemetry with explicit thresholds | **UNVERIFIED.** Sampler tests pass, but `scripts/soak/run_soak.py:1410–1422` measures driver-loop lag, not application-loop latency. No complete deployed time series or threshold evaluation performed. |
| Kill/restart during active work, graceful drain/fencing/recovery | **UNVERIFIED.** Boot-cleanup and drain-gate regressions pass; these are not active physical-work crash/recovery observations. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** Assignment designates source refs, not the immutable promoted artifact/configuration. `scripts/soak/run_soak.py:730–741` rejects host preflight. Executed synthetic four-hour CLI test proves rejection, not an elapsed four-hour run. |
| Findings filed/reclassified | Local evidence recorded here; external filing/reclassification **UNVERIFIED**, GitHub mutations prohibited. Historical schema failure no longer reproduces: current test independently includes the three audit-column upgrades at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176–178`. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED.** This source-linked validation report is not a hash-bound deployed RC soak evidence pack. |

## Disposition and handoff

**BLOCKED.** Only this report changed. No tests added or altered, so no inventory
delta is required. No scanner failure or schema regression currently justifies
production/test/ledger changes. No develop-sync conflict was present. Inherited
work is preserved. This is not integration approval.

Required next input: a release-owner-designated immutable RC artifact and
runtime configuration, with representative-workload applicability. Remaining
implementation includes a production-topology runner, physical-work/recovery
oracles, complete telemetry, and reconciliation of the rate-budget contract.
Then execute an unchanged >=14400-second multi-replica soak and publish its
hash-bound evidence. Repeating only schema/vulture validation cannot resolve
this blocker.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0; next: obtain RC designation and finish production-soak
capability, not another speculative ledger amendment.
