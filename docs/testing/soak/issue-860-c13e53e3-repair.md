# Issue #860 — bounded repair c13e53e3

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head
  `eee9aad11359b4d004f4a886410ce69780a2c303`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect existing soak runner/profile, adjacent promotion tests, repository
  instructions and relevant ADRs; run the exact requested vulture gate and
  focused validation. Amend the ledger only for actual reviewed findings.
- Intended edit surface: this report; `quality/vulture-baseline.json` only if
  the exact scan demonstrates retained unbanked identities. No runtime repair
  is assumed necessary before evidence. No external issue or PR mutations.
- Starting worktree is clean; no incoming diff needs salvage.
- Current job directory contains no `check-*.log` at initial snapshot. Read
  the explicitly supplied previous failed log instead.
- Ambiguity: no immutable RC artifact/configuration is supplied in the lane
  brief. A local test run will not be represented as an exact-RC soak.

## Progress

Read supplied prior result: it reports BLOCKED, not promotion evidence.
Acceptance and fresh command results will be recorded below.

- `uv sync --locked --extra dev`: exit 0.
- Exact requested vulture scan: exit 0; 1323 findings, 1323 reviewed identities,
  zero unclassified. No evidence supports a ledger amendment.
- Historical `check-3.log` reports 24 versus 21 schema DDL statements, not a
  vulture failure. The current regression will be executed independently.
- Read accepted ADR-085 and lease ADRs ADR-081626-f383 / ADR-082526-b36a.
  The Run store owns fencing and the executor owns heartbeat/reclaim integration;
  admission identity alone is not proof of physical-effect uniqueness.
- Candidate profile path `scripts/soak/m3a-load-profile.md`: not found; skipped.
  Resolve the documented profile filename once before inspection.
- Logs: `/tmp/860-c13e53e3-{sync,vulture}.log`.
- `uv run ruff check .` and `uv run ruff format --check .`: exit 0.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: 111 passed, 6 skipped (migrated PostgreSQL DSN not configured).
  The historical schema assertion passes. No live database result is claimed.
- `uv run python scripts/check-suite-inventory.py` and
  `uv run python scripts/check-deployment-claims.py`: exit 0.
- Validation used 1200-second command timeouts. Logs:
  `/tmp/860-c13e53e3-{ruff,format,tests,inventory,deployment}.log`.
- Resolved and read `docs/testing/soak/m3a-load-profile.md`, production
  middleware, runner artifact gate, schedule cleanup and sustained-load path,
  and all adjacent promotion-gate tests. No test additions or inventory delta.

## Acceptance audit and reconciliation

The frozen dispatch issue body contains ten criteria. Passing deterministic
checks is not a replacement for executing them on the designated RC.

| Criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` names missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. `scripts/soak/run_soak.py:1381` still runs a narrower degraded mix. No selected-RC applicability decision is supplied. |
| Two application replicas | **UNVERIFIED at deployment level.** Two real middleware instances pass the focused tests, but no deployed RC pair was loaded this round. |
| Sustained saturation, growth, reclaim, backoff and leaks | **UNVERIFIED.** Sampler tests exercise resource observation, not long-window production saturation/recovery. |
| No duplicate physical work | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without executing it. Admission uniqueness does not establish Attempt/Goal/physical-effect uniqueness. |
| Rate/security/degraded non-bypass | **UNVERIFIED as a whole; independent allowances demonstrated.** `tests/test_soak_promotion_gates.py:439` freshly passes for authenticated and unauthenticated identities: each replica accepts two requests then rejects the third. `packages/maistro-server/src/maistro_server/main.py:648` installs this production middleware; `api/rate_limit.py:93` constructs its process-local limiter. |
| Complete telemetry and thresholds | **UNVERIFIED.** Profile thresholds exist, but no new production series was collected. `scripts/soak/run_soak.py:1410` observes driver-loop lag, not application-loop lag. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** Cleanup and boot-contract tests passed, but no active physical-work kill/recovery experiment ran. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** No designated immutable RC/configuration is supplied. `scripts/soak/run_soak.py:730` explicitly rejects host-process preflight as exact-RC evidence; the synthetic four-hour CLI tests freshly pass by rejecting such evidence. |
| Findings filed/reclassified | Local disposition recorded here: stale schema failure does not reproduce; exact ledger matches; rate-scope and production-evidence gaps remain. External filing/reclassification **UNVERIFIED**; GitHub mutations are prohibited. |
| Hash-bound machine/human RC evidence | **UNVERIFIED.** Local logs and this report describe source validation, not an image/config-bound production soak bundle. |

Accepted ADR-085 requires canonical per-principal identity. The current documented
process-local budget is not proof of #860's stronger replica-selection non-bypass
claim. No new authorization path or shared limiter is introduced under a soak
repair assignment. Accepted lease ADR-082526-b36a extends the earlier fencing
boundary with renewal/reclaim; neither admission counters nor process rejoin waive
physical-work recovery acceptance. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt` and the canonical Run store's execution authority.

## Handoff

**BLOCKED**, not integration approval. Changed file: this report only. The exact
CI vulture arguments match both quality workflows, and the scan needs no ledger
amendment. No production, test, inventory, grant or runtime configuration changed.
Deployment-claims validation proves named components exist, not live readiness.
Inventory validation matched 17 suites / 31128 unique test identities, with no
copied-test duplication. Ruff checked successfully; 3270 files were formatted.

Next: supply the immutable RC/configuration, settle the replica-budget acceptance
contract, complete representative workloads and physical-effect/recovery and
application-telemetry oracles, then run the unchanged deployed RC for at least
14400 seconds and publish the hash-bound bundle. A longer host-process preflight
cannot resolve these blockers. No Docker availability limitation is asserted.

Checkpoint: checked 1 issue; acceptance-complete 0; skipped issues 0; unresolved
validation-command failures 0. One candidate profile path was not found and was
resolved once as recorded above. All 111 executed tests passed; 6 live-PostgreSQL
tests remain explicitly skipped. This report is committed locally as the bounded
writer handoff; the missing acceptance evidence remains unresolved.
