# Issue #860 — bounded repair 48a9d07e

## Frozen scope

- Only issue #860; branch `auto-860`; starting HEAD
  `e95509f46a1a60ae04ba93623badb9623eeb195d`; supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolved locally).
- Starting worktree clean; no incoming uncommitted changes to salvage.
- Inspect the supplied dispatch snapshot and prior result/log, repository instructions,
  relevant accepted ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and the production learnings store plus its tests.
- Candidate edits limited to evidenced repairs in those files, the explicitly permitted
  `quality/vulture-baseline.json` if the exact scan finds retained identities,
  required inventory notes, and this report. No other issue/PR processing.
- No `check-*.log` files were present in this job directory at the initial snapshot.
  Supplied prior `98a11313.../check-3.log` reports 24 schema statements against 21 expected.
- Assumption: this is a writer CI-repair round, not permission to select a release
  artifact, change deployment/security policy, or claim promotion readiness.

## Progress

Initial inspection complete. Prior result is BLOCKED on exact-RC soak evidence.
Earlier verification claims are not accepted as current validation.

Fresh validation: exact vulture command passed (1323 findings, 1323 reviewed
identities, zero unclassified); no ledger amendment justified. The reported
schema failure does not reproduce: `uv run pytest
packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed
37 tests, skipped 6. Current test lines 176–178 already independently enumerate
the three Gauntlet audit columns missing from the historical failure. No schema
repair is justified. Logs: `/tmp/860-48a9-vulture.log` and
`/tmp/860-48a9-learnings.log`.

## Architecture

Read accepted ADR-073126-c4e1 (immutable RC artifacts and promotion),
ADR-082526-b36a (executor renewal and reclamation), and ADR-085 (principal
rate limits). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and its
existing authorities. Admission deduplication is not physical-work fencing;
a local build is not a designated release artifact. The documented local rate
budget is narrower than the issue's replica-selection non-bypass criterion;
this is an unresolved acceptance gap, not permission to introduce another
authorization path or waive acceptance.

## Fresh commands and outcomes

Commands used 600- or 1200-second timeouts; all exited zero.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1323 reviewed findings, zero unclassified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  — 37 passed, 6 skipped (PostgreSQL-dependent cases; no live DB proof claimed).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
  — 74 passed. Includes actual production limiter instances, process-group
  sampling with a real child process, and fail-closed preflight CLI checks.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py` — 17 suites match;
  31128 unique identities, zero duplicate evidence.
- `uv run python scripts/check-deployment-claims.py` — passed; verifies component
  existence, not deployed concurrency.

Logs are `/tmp/860-48a9-{vulture,learnings,soak-tests,ruff,format,inventory,deployment}.log`.

## Acceptance audit

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one key and a health/task/receipt/metrics mix; `docs/testing/soak/m3a-load-profile.md:152` records missing users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. |
| At least two application replicas | **UNVERIFIED.** Two real middleware instances were tested in-process, not two deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks | **UNVERIFIED.** Sampler regression passes, but no sustained deployment run was executed. |
| No duplicate physical work | **UNVERIFIED.** Admission tests pass; `scripts/soak/run_soak.py:1044–1068` cancels the unexecuted schedule probe through the canonical store. This cannot demonstrate physical effects or Attempt fencing. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; independent allowances reproduced.** `tests/test_soak_promotion_gates.py:439` obtains 200,200,429 from each production middleware instance for the same identity; `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs the local limiter. Task backpressure tests pass but do not prove cluster-wide security. |
| Complete telemetry and thresholds | **UNVERIFIED.** Resource sampler tests pass; `scripts/soak/run_soak.py:1410–1422` measures driver-loop lag, not application-loop latency. No complete RC time series evaluated. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED.** Boot-cleanup and drain-evaluator tests are not a crash/recovery experiment during physical work. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** Assigned refs do not designate the immutable promoted artifact/configuration. `scripts/soak/run_soak.py:730–741` explicitly rejects host preflight. Executed synthetic four-hour test proves rejection, not four hours of elapsed load. |
| Findings filed/reclassified | Local evidence recorded; external filing/reclassification **UNVERIFIED**. GitHub mutations prohibited. Historical schema failure no longer reproduces. |
| Hash-bound machine/human RC evidence | **UNVERIFIED.** This source-linked validation record is not an RC soak evidence pack. |

## Handoff

**BLOCKED**, not promotion or integration approval. Only this report changed;
no test additions or edits, so no inventory delta is required. No evidence
justifies modifying production, tests or the vulture ledger in this repair.
No sync conflict exists. Inherited changes remain intact.

Next: obtain release-owner-designated artifact/configuration and workload
applicability; finish the production-topology runner, physical-effect/recovery
oracles and complete telemetry; reconcile the rate-budget requirement; then run
an unchanged >=14400-second multi-replica soak and publish hash-bound evidence.
Repeated clean CI scans cannot satisfy these missing acceptance criteria.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
errors 0 validation commands; next is the blocked RC evidence work above.
