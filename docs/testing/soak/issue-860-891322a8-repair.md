# Issue #860 — bounded repair 891322a8

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `f6ecced8222a253f40ac3317c64f72f7fdb330e7`; supplied base:
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. Both resolve locally.
- Starting worktree clean. No salvage or develop-sync conflict exists.
- Evidence snapshot: supplied `dispatch-context.json`, previous result
  `b08ee82ce6474ec28ad10087f513250f/result.json`, and reported
  `98a11313167b41a98a420abfda80c292/check-3.log`. Current job directory had
  no `check-*.log` files at initial inspection.
- Process the reported schema-fence failure, the requested Vulture scan, and
  focused validation of existing soak acceptance guards. No other issues/PRs.
- Potential implementation files: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`, and
  `quality/vulture-baseline.json` only if actual scan findings require review.
  Additional acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, existing load profile, server task/rate
  middleware and adjacent tests. Inventory note only if tests change.

## Initial evidence and assumptions

The supplied earlier check failed because schema DDL count was 24 rather than
21. That is historical evidence, not proof of a current failure. The previous
result was BLOCKED on missing exact RC identity/configuration and unproven
multi-replica behavior, not on a merge conflict. Assume no authorization to
invent an RC identity or change production topology; preserve fail-closed
promotion gates and canonical Goal -> Graph -> Run -> NodeRun -> Attempt.

## Validation and acceptance

Fresh results so far:

- `uv sync --locked --extra dev`: pass.
- Prescribed Vulture command: pass, 1323 findings / 1323 reviewed identities,
  zero unclassified. No ledger amendment warranted by actual scan evidence.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **111 passed, 6 skipped** in 2.55 seconds. Database-dependent skips explicitly
  require `MAISTRO_TEST_PG_DSN`.
- Historical schema failure does not reproduce. The expected DDL already lists
  the three validation audit columns at `test_pg_learnings.py:179–181`, matching
  production. Do not remove columns or weaken the assertion to repair a stale log.

- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: pass, 17 suites, 31128
  unique test identities, zero duplicate evidence.
- `uv run python scripts/check-deployment-claims.py`: pass; verifies named
  components exist, not deployed behavior.
- `git diff --check`: pass.

Commands used 1200-second timeouts. CI gate arguments checked in
`.github/workflows/{quality,vulture-ratchet,ci}.yml`. No code, tests or ledgers
changed; there is no new test inventory delta.

## Architecture reconciliation

Read repository instructions, `docs/README.md`, accepted ADR-085,
ADR-081626-f383 and ADR-082526-b36a. Preserve the canonical execution spine:
the Run store owns lease/fence authority and the executor owns renewal. The
later lease ADR establishes reclaim obligations; the earlier boundary is not
a waiver of recovery testing. Admission deduplication alone cannot prove
physical-work uniqueness. ADR-085 specifies principal identity for limits;
the process-local implementation does not prove the stronger #860
replica-selection non-bypass criterion. No alternate execution or authorization
mechanism was introduced to paper over that discrepancy.

## Acceptance audit (freshly checked, not inherited claims)

| #860 criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:152` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. `run_soak.py:1381` implements the limited health/task/receipt/metrics mix with one credential. No selected-RC applicability decision is supplied. |
| At least two deployed application replicas | **UNVERIFIED**. Boot-contract tests pass, but ASGI middleware instances are not deployed RC replicas; no designated RC deployment executed this round. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff and leaks | **UNVERIFIED**. The real child-process sampler test passed; fast tests cannot establish long-window production behavior. No sustained load executed this round. |
| No duplicate physical work across replicas | **UNVERIFIED**. Admission probe tests pass, but `run_soak.py:1044` cancels the schedule probe's queued Run without executing work. Task/Attempt/Goal physical effects still need an observable production oracle. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**. Executed `test_soak_promotion_gates.py:439` for both identity classes: after replica 1 returns `[200, 200, 429]`, replica 2 independently returns `[200, 200, 429]`. Production `api/rate_limit.py:93` creates independent in-memory state, installed by `main.py:648`. Local 429 enforcement is proven, not a cluster-wide budget. |
| Full telemetry and explicit thresholds | **UNVERIFIED**. Profile thresholds exist. `run_soak.py:1410` samples driver-loop lag, not application-loop lag. No complete fresh production pool/query/lock/queue/worker/error time series or threshold judgment. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Boot cleanup and promotion-gate tests pass; no active physical-work restart/recovery experiment executed. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED**. No designated immutable RC digest/configuration supplied. `run_soak.py:730` always fails exact-artifact evidence for the host topology. Executed synthetic four-hour CLI tests prove rejection, not four hours of real traffic. |
| Findings filed/reclassified before promotion | Locally recorded here; external filing/reclassification **UNVERIFIED**. No GitHub mutations allowed. Historical schema failure is already repaired; no new Vulture debt. Rate-budget discrepancy and evidence gaps remain. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED**. This report records local validation at the starting HEAD, not a hash-bound production soak bundle. |

## Handoff

**BLOCKED**, not merge-ready. Only this report changes; the inherited branch
and its evidence are preserved, not blanket-certified. No actual scanner or
schema-test failure justified another repair. Do not re-dispatch the stale
21-versus-24 DDL failure as if it still exists.

Next actionable input: designate immutable RC images and runtime configuration,
resolve the replica-budget contract, complete the representative workload and
physical-effect/recovery/application-telemetry oracles, then execute at least
14400 seconds on the unchanged production artifact. Docker unavailability is
not asserted; a host shakedown cannot replace those missing prerequisites.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands; 6 database-dependent tests skipped. Local commit
is a writer handoff only, never integration or promotion approval.
