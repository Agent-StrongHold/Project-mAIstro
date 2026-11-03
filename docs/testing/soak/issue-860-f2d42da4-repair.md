# Issue #860 — f2d42da4 repair checkpoint

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `9d2f65012defc3ff39ed6ab6f002eee3b2d35c2c`, assigned base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree was clean. No salvage patch required.
- Read the supplied dispatch snapshot and previous result; no remote mutations
  or refreshed issue/PR enumeration.
- Assigned job directory contained no `check-*.log` at initial inspection.
- Repair surfaces frozen to this report and, only if fresh scan evidence warrants
  it, `quality/vulture-baseline.json` and the identities reported by that scan.
  Existing soak harness/tests, production rate limiter, and relevant ADRs are
  read/validation surfaces, not permission for a new execution authority.
- Ambiguity: prior result says BLOCKED, not a merge conflict. Assume this round
  requests fresh CI repair validation plus acceptance audit, not an unrequested
  develop merge or designation of an RC artifact.

## Results

Fresh exact vulture command passed: 1323 findings / 1323 reviewed identities,
zero unclassified (`vulture.log` in this job directory). No identity amendment
is warranted; do not change a passing ledger speculatively. The historical
`98a11313/check-3.log` is a schema-fence test failure (24 DDL statements versus
21 expected), not a scanner finding. Fresh focused pytest passed: 111 passed,
6 skipped (live PostgreSQL tests require `MAISTRO_TEST_PG_DSN`). The historical
schema assertion failure does not reproduce. Read accepted ADR-085 and
ADR-082526-b36a: principal limits and renewable/fenced Attempt leases remain
canonical; admission counts cannot substitute for physical-work proof.
The current schema test independently lists the three validation audit columns
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176`.

## Executed validation

All commands ran in the assigned worktree with 1200-second timeouts. Logs are
under `/home/dev/maistro/jobs/f2d42da40e8445c6a1be82fb37b800c5/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; exact workflow arguments at `.github/workflows/vulture-ratchet.yml:82`; 1323 identities, zero unclassified |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 111 passed, 6 skipped in 2.63 s; no live PG proof |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | PASS; all 17 suites match, 31128 unique identities |
| `uv run python scripts/check-deployment-claims.py` | PASS; named components/backends exist, not deployment behavior proof |

No tests were added or changed; no inventory delta is required. This report is
the only changed file. No ledger, source, gate or grant change was justified.

## Acceptance audit against reachable behavior

| #860 criterion | Current evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Read `docs/testing/soak/m3a-load-profile.md:152` and `scripts/soak/run_soak.py:1381`: one-key health/task/degraded mix omits multi-user Workspaces, graph fan-out, successful tool/model, Design/Canvas and background/Goal workloads. No selected-RC exclusions supplied. |
| Two deployed application replicas | **UNVERIFIED.** Fresh middleware tests instantiate two ASGI apps, not deployed RC replicas. No deployment ran this round. |
| Sustained saturation/queue/reclaim/retry/leak observations | **UNVERIFIED.** Unit sampler and backpressure tests pass; these do not observe a sustained deployed workload. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule admission probe Run without execution. Deduplicated admission is not a physical-effect oracle. |
| Rate/security/degraded non-bypass by replica selection | **UNVERIFIED overall; independent allowances reproduced.** Fresh `tests/test_soak_promotion_gates.py:439` exercises the production middleware and gets `[200,200,429]` separately on each replica for the same authenticated or unauthenticated identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs instance-local state. Local six-path enforcement is not a shared allowance. |
| Full telemetry with thresholds | **UNVERIFIED at RC level.** Profile specifies thresholds; `scripts/soak/run_soak.py:1410` measures driver-loop lag, not application-loop lag. No fresh RC connection/lock/worker/queue/RSS/fd/error series collected. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED.** Boot and promotion regression tests pass, but no deployed active-work fault injection ran. Rejoin/terminal counts alone cannot prove physical recovery. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** No immutable promotion image/runtime configuration designated in the assignment. `scripts/soak/run_soak.py:730` explicitly rejects host-process evidence; passing fail-closed regressions do not certify an RC. |
| Findings filed/reclassified before promotion | Local audit recorded here; external filing/reclassification **UNVERIFIED**, GitHub mutations prohibited. Historical schema failure does not reproduce; vulture has no current mismatch. |
| Hash-bound machine/human soak publication | **UNVERIFIED.** Fresh source-validation logs and this human report are not a hash-bound exact-RC soak bundle. |

## Disposition and next prerequisite

**BLOCKED.** Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and the
existing authorization path. Accepted lease ADR requires renewal and fenced
recovery, not a second scheduler or an admission-only substitute. ADR-085's
principal identity contract does not establish a cluster-wide allowance from
independent process-local budgets. Resolve that deployment contract explicitly
without weakening gates.

No merge conflict or stale scanner failure needs repair here. Repeating a
host-process smoke run cannot meet the exact-RC acceptance even at four hours;
no Docker availability claim is made. Next: designate immutable RC/configuration,
complete representative workloads, physical-effect/recovery oracles and app
telemetry, resolve replica-budget semantics, then execute the unchanged deployed
RC for at least 14400 seconds and publish hash-bound evidence. This writer
checkpoint is not integration approval.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; validation
command failures 0; live-PG test skips 6. Commit this blocked handoff locally.
