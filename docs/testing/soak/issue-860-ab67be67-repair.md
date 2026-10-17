# Issue #860 — ab67be67 validation checkpoint

## Frozen scope

- Assigned issue #860 only, branch `auto-860`, starting HEAD
  `62a0f2f56e968d85e046524d6b5b6c451c6c6457`, base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial working tree clean; no incoming edits to salvage.
- Supplied job snapshot only; no refreshed issue/PR enumeration or GitHub mutations.
- Initial job directory has no `check-*.log`. Read the explicitly supplied
  historical `98a11313/check-3.log`: schema-fence assertion counted 24 DDL
  statements against 21 expected. This is not vulture evidence.
- Read previous `f2d42da4/result.json` and committed checkpoint as claims to
  verify, not proof. Prior block is exact-RC acceptance, not a sync conflict.
- Frozen write surfaces: this checkpoint; `quality/vulture-baseline.json` and
  specific reported source identities only if fresh required scan demonstrates
  a mismatch. Existing schema, soak, boot and backpressure tests are validation
  surfaces. No speculative gate, ledger, execution or authorization changes.
- Assumption: no immutable RC/configuration has been designated by this repair
  assignment. Do not invent one or call a host-process smoke run promotion proof.

## Fresh validation

Commands ran in the assigned worktree with 1200-second timeouts. Logs are in
`/home/dev/maistro/jobs/ab67be675ee04b82bb1181387e38b6a1/`.

| Command | Executed result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 findings / 1323 reviewed identities, zero unclassified; `vulture.log`. Exact workflow arguments verified at `.github/workflows/vulture-ratchet.yml:82`. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 111 passed, 6 skipped in 2.48 s; `pytest.log`. Skips require `MAISTRO_TEST_PG_DSN`; not live PostgreSQL proof. |
| `uv run ruff check .` | PASS; `ruff-check.log` |
| `uv run ruff format --check .` | PASS: 3270 files already formatted; `ruff-format.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 31128 unique identities; `suite-inventory.log` |
| `uv run python scripts/check-deployment-claims.py` | PASS: named components/backends exist; `deployment-claims.log`. Not deployed behavior proof. |

Historical schema failure does not reproduce. The independent DDL expectation
now includes all three validation-audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:176`, matching
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:116`.
No dead identity, stale ledger entry, or code defect in the assigned CI failure
was demonstrated. No ledger amendment is warranted. No tests changed or were
added, so no inventory-delta note is required.

## Architecture and acceptance audit

Read repository instructions, documentation authority map, accepted ADR-085 and
ADR-082526-b36a, the load profile, production limiter/schema paths and adjacent
regression tests. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The lease ADR requires renewable, fenced Attempt recovery; admission uniqueness
is not physical-work uniqueness. ADR-085 keys limits to principals; the existing
process-local implementation does not prove a shared replica-independent budget.
No alternative scheduler or authorization path is introduced to bridge these gaps.
The snapshot's PR #1672 body is only a draft claim-stake and its last three issue
comments do not designate an immutable RC; the assignment remains insufficient
to select the artifact #89 would promote.

| Issue acceptance criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` identifies missing users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. Source mix at `scripts/soak/run_soak.py:1381` confirms narrow preflight traffic. No selected-RC exclusions supplied. |
| At least two deployed application replicas | **UNVERIFIED.** Fresh middleware tests use two ASGI instances, not deployed RC replicas; no deployment ran this round. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks and restart observations | **UNVERIFIED.** Sampler/backpressure regressions pass, but no sustained deployed workload ran. |
| No duplicate physical work across schedules/tasks/Runs/Attempts/Goals | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without execution. Admission-only probes cannot establish physical-work fencing. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; independent budgets reproduced.** Fresh `tests/test_soak_promotion_gates.py:439` exercises production middleware with the same principal/client on two replicas and asserts `[200,200,429]` independently. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs instance-local state. Six-path local rejection is not a shared budget. |
| Required telemetry with explicit thresholds | **UNVERIFIED at RC level.** Profile defines thresholds; process-group sampler tests pass. `scripts/soak/run_soak.py:1410` measures driver-loop lag, not application-loop lag. No fresh deployed connection/lock/worker/queue/RSS/fd/error series collected. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Boot/fail-closed regressions pass, but no deployed fault injection or physical-effect recovery oracle ran. |
| Long-running unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** Immutable promotion artifact/configuration not designated. `scripts/soak/run_soak.py:730` always rejects host-process preflight as exact RC; freshly executed four-hour synthetic-evidence tests verify that rejection, not a four-hour soak. |
| Findings filed/reclassified before promotion | Local findings recorded here; external filing/reclassification **UNVERIFIED**, GitHub mutation prohibited. Historical schema failure does not reproduce and scanner has no current mismatch. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED.** Fresh local validation logs plus this report are not a hash-bound exact-RC soak bundle. |

## Disposition

**BLOCKED.** Only this checkpoint changed. No production repair or cosmetic
ledger change is justified by the actual checks. Do not retry this as a stale
vulture/schema failure: both pass. Next prerequisite is an immutable RC/config
selection plus complete production-path workload, physical-effect/recovery and
application-telemetry coverage; resolve replica-budget semantics before an
unchanged >=14400-second deployed soak and hash-bound evidence publication.
A longer host-process preflight cannot meet that contract.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0; live-PG test skips 6. Local checkpoint commit is required;
this report is not integration approval.
