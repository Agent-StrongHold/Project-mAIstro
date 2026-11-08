# Issue #860 repair — b121f2c8

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`6f299af43881427a6fb5c308d90cac4551e9f2e5`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Worktree initially clean.
No remote mutations or ref enumeration. Current job has no check-*.log files.
Read supplied prior check-3.log: schema-fence test expected 21 DDL calls,
observed 24. This is historical evidence, not a current failure claim.

Repair file snapshot: this report; `quality/vulture-baseline.json` only if the
required scan identifies reviewed retained debt; `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, and an inventory
note only if the reported schema regression reproduces. Read-only acceptance
review: supplied dispatch, repository instructions, ADRs, soak runner/profile,
promotion tests, rate-limit middleware and relevant CI/check scripts.

Assumption: this is a writer CI-repair round, not authorization to designate an
immutable release candidate or invent deployment acceptance evidence. Prior
BLOCKED result is to be rechecked, not assumed true.

## Results

- Exact required vulture command: exit 0, 1323 reviewed identities and 1323
  findings, zero unclassified. No justified ledger amendment.
- Focused pytest (schema persistence, soak promotion gates, production boot
  contract, task concurrency backpressure): exit 0. Historical schema failure
  no longer reproduces; current expectation includes all three validation-audit
  columns. No speculative production/test repair is warranted.
- Fresh logs are in the supplied job directory as `validation-vulture.log`
  and `validation-tests.log`.
- Profile explicitly disclaims exact-RC execution and documents missing
  representative workloads. Reviewed the corresponding reachable runner and
  production rate-limit wiring, not only earlier reports.

## Executed validation

All commands ran in the assigned worktree with 1000–1200 second timeouts.
Fresh logs reside in the supplied job directory, not in the repository.

| Command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323 identities; `validation-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 111 passed, 6 skipped; `validation-tests.log` |
| `uv run ruff check .` | PASS; `validation-ruff.log` |
| `uv run ruff format --check .` | PASS, 3270 files; `validation-format.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 31128 unique identities; `validation-inventory.log` |
| `uv run python scripts/check-deployment-claims.py` | PASS; `validation-deployment.log` |
| `git diff --check` | PASS |

The six skips explicitly require `MAISTRO_TEST_PG_DSN` pointing at a migrated
PostgreSQL database. They are not live database acceptance evidence. No new
tests, inventory delta, production code or ledger changes were justified by
these results. CI workflow arguments match the executed vulture scan.

## Acceptance audit

| Frozen issue criterion | Evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` lists missing users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads. `scripts/soak/run_soak.py:1381` still uses a narrower degraded mix. |
| At least two supported application replicas | **UNVERIFIED at deployed RC level.** Tests execute two independent real middleware instances, not two deployed RC applications. No deployment was started this round. |
| Sustained saturation, growth, lease reclaim, retries and leaks | **UNVERIFIED.** Deterministic sampler/admission tests passed; no long-window production load ran. |
| No duplicated physical work across replicas | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without executing it. Admission uniqueness is not physical Attempt/Goal-effect uniqueness. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; independent replica allowances freshly demonstrated.** `tests/test_soak_promotion_gates.py:439` passed for both authenticated and unauthenticated identities, observing `[200,200,429]` on each replica. Production installs that middleware at `packages/maistro-server/src/maistro_server/main.py:648`; its instance-local limiter is constructed at `api/rate_limit.py:93`. |
| Required telemetry and thresholds | **UNVERIFIED.** Existing profile thresholds are not newly measured RC series. `scripts/soak/run_soak.py:1410` measures driver-loop lag, not application event-loop lag. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED.** Boot and promotion-gate tests passed; no active-work kill/recovery experiment ran. Process rejoin is not proof of physical-work recovery. |
| Long soak of unchanged exact RC artifact/configuration | **BLOCKED / UNVERIFIED.** Lane brief designates source commits, not the immutable image/configuration to promote. `scripts/soak/run_soak.py:730` unconditionally rejects host-process preflight as exact-RC evidence. Passing fail-closed tests cannot supply a production soak. |
| Findings filed/reclassified before promotion | Local disposition recorded here: stale schema failure does not reproduce, vulture ledger matches, acceptance gaps remain. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED.** Fresh logs and this source-validation report are not a hash-bound deployed RC soak bundle. |

## Architecture reconciliation and handoff

Read accepted ADR-085 and ADR-082526-b36a. Preserve canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt`, principal identity resolution,
and executor/store heartbeat, reclaim and fencing authority. The documented
process-local request budget is not proof of the issue's stronger
replica-selection non-bypass claim. No alternative limiter, scheduler, Goal
store or authorization path is introduced as an unrequested soak repair.
Accepted lease semantics require liveness and fenced recovery; neither admission
counts nor healthy restart waive that requirement.

**BLOCKED.** Only this report changed. Historical schema failure is resolved in
the starting tree; exact-debt-ledger repair is unnecessary because the fresh
required scan passes. Do not repeatedly retry this same stale check as though
it identifies a current repair. This report is a local writer handoff, never
integration or promotion approval.

Next prerequisite: designate immutable RC image/configuration and resolve the
replica-budget contract; complete representative workloads, physical-effect and
recovery oracles, and application-side telemetry; run the unchanged deployed RC
for the profile's minimum 14400 seconds and publish its hash-bound evidence.
No Docker-availability limitation is asserted. Extending the host-process
preflight duration cannot meet exact-RC acceptance.

Checkpoint: checked 1 issue; acceptance-complete 0; skipped issues 0;
validation-command errors 0; six live-PG tests skipped as reported. Commit this
report locally; retain the existing implementation and evidence unchanged.
