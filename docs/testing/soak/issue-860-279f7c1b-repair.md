# Issue #860 — repair audit 279f7c1b

## Frozen scope

One item: issue #860, branch `auto-860`, starting head
`8e5c3ccb874f45a9f928d6a555849e0e4701da1e`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Initial worktree clean; no salvage necessary. No GitHub mutations.

Files in scope: this report; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`,
`docs/testing/soak/m3a-load-profile.md`, relevant repository/ADR guidance,
and the explicitly authorized `quality/vulture-baseline.json` only if the
exact scanner demonstrates a required amendment. Existing prior artifacts
are evidence, not proof of current acceptance. No new issue/PR enumeration.

Supplied current job directory contains no `check-*.log` files. Inspect the
explicitly supplied prior `check-3.log` and rerun its gate locally.
Assumption: this is a writer CI-repair round, not permission to designate an
RC or substitute local preflight for deployment evidence.

## Progress

- Confirmed exact starting HEAD and clean worktree.
- Read supplied prior result: BLOCKED, with exact-RC soak unverified.
- Read complete issue acceptance body from frozen dispatch context.
- Exact required vulture command passed: 1323 reviewed identities / 1323
  findings, zero unclassified. No ledger amendment justified.
- Historical `check-3.log` fails the learnings schema test (24 statements
  versus 21). Current focused rerun passes: 111 passed, 6 skipped in 2.49s.
  Skips require a migrated PostgreSQL DSN; no database acceptance inferred.
- Read-only validation also includes the schema and task-backpressure tests
  named by the prior failure/report; no edits to their production or test
  files are justified.

## Architecture and reconciliation

Read repository `AGENTS.md`, accepted ADR-073126-c4e1 (release provenance),
ADR-082526-b36a (renewable leases and reclamation), and ADR-085 (principal
rate limiting). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
An arbitrary local source build cannot substitute for the RC artifact the
release process will promote. Admission deduplication and process rejoin do
not prove physical-work fencing. The middleware's documented process-local
budget is narrower than #860's replica-selection non-bypass requirement;
passing local enforcement tests does not waive that acceptance criterion.
No alternate authority, scheduler, store or authorization path introduced.

## Executed commands

Validation commands used 1200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1323 reviewed identities / findings, zero unclassified. Matches
  `.github/workflows/vulture-ratchet.yml:82`. Leave ledger unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
  — PASS, 111 passed / 6 skipped in 2.49s. Skips require
  `MAISTRO_TEST_PG_DSN`; no deployed PostgreSQL claims proven.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py` — PASS, 17 suites,
  31128 unique identities, no duplicate evidence. No tests changed or added;
  no inventory delta required.
- `uv run python scripts/check-deployment-claims.py` — PASS. Component
  existence only, not proof of deployment behavior.

## Acceptance audit

| Criterion | Executed evidence / gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** Read actual request mix at `scripts/soak/run_soak.py:1373–1395`: one credential, health/task/receipt/metrics traffic. `docs/testing/soak/m3a-load-profile.md:152` identifies missing users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads. |
| Two deployed replicas | **UNVERIFIED.** Tests execute separate production middleware instances in ASGI, not two deployed RC replicas. No deployed soak run this round. |
| Sustained saturation, queues, reclaim, retry, leaks | **UNVERIFIED.** Existing process-group sampler test executes a real wrapper/child and verifies memory/fd growth. This is not sustained saturation/reclaim/leak observation. |
| No duplicate physical work | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1068` cancels the unexecuted schedule-probe Run. Passing admission tests does not prove physical effects, Attempt fencing or Goal reconciliation. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439`: the same identity receives 200,200,429 independently from each middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs an in-memory limiter per instance. Task-backpressure tests prove only the narrower retryable-429 path. |
| Complete telemetry and thresholds | **UNVERIFIED.** Sampler tests pass, but `scripts/soak/run_soak.py:1410–1422` samples driver-loop lag, not application-loop latency. No complete deployed time series audited this round. |
| Active-work kill/restart, drain, fencing, recovery | **UNVERIFIED.** Boot cleanup and drain-gate tests pass, not a deployed restart with active physical work and loss/duplication oracles. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** No immutable promoted artifact/configuration is designated by this assignment. `scripts/soak/run_soak.py:730–741` explicitly rejects host preflight. Executed synthetic four-hour CLI regression proves rejection, not elapsed soak duration. |
| Findings filed/reclassified | Local audit recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. Historical schema mismatch no longer reproduces: current expectations include the three audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176–178`. |
| Hash-bound machine/human soak evidence | **UNVERIFIED.** This source-linked check report is not an image/package/config-bound deployed RC evidence pack. |

## Disposition

**BLOCKED.** Only this report changed. No speculative production, test or
ledger edits. Existing work preserved. There is no develop-sync conflict to
resolve and no failing scanner identity to bank.

Required next input: release owner designates the immutable RC artifact and
runtime configuration, plus workload applicability. Remaining work is the
production-profile workload/telemetry/fencing oracle, rate-budget contract
reconciliation, and an unchanged >=14400-second deployed multi-replica run
with hash-bound evidence. Another schema/vulture-only repair cannot establish
those acceptance criteria. Do not treat this checkpoint as integration approval.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0. Initial `git diff --check` caught an extra EOF blank
line in this report; removed before commit. Local audit completed;
acceptance remains blocked.
