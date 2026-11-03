# Issue #860 repair — a6563121

## Frozen scope

- Only issue #860, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD `3ecad54246d9d3efd6c902b8c1292ae9adabc5f6`; supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean; no incoming edits to salvage.
- Evidence snapshot: job `a656312176914e02b748d25090017b18/dispatch-context.json`, prior result `48a9d07efa8546cd94b94c615ce89131/result.json`, supplied failed `98a11313167b41a98a420abfda80c292/check-3.log`.
- No `check-*.log` in current job directory at start.
- Production/test inspection limited to the schema fence, soak runner and promotion tests, associated ADRs/profile, and exact vulture gate. Conditional edit surfaces: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` only for observed retained identities, an inventory note if tests change, and this report. No other issues/PRs will be processed.

## Initial evidence and assumptions

The supplied check-3 failure expected 21 DDL calls but production emitted 24. Reproduce before repair; do not weaken the fence or remove valid schema upgrades. Prior BLOCKED verdict is not proof of current behavior. Exact-RC promotion evidence must not be inferred from unit tests or host preflight. No designated RC deployment/configuration is included in the lane brief; inspect the frozen dispatch for any designation before claiming one.

## Fresh validation checkpoint

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**, exit 0. Historical failure does not reproduce. Current independent DDL expectation already contains the three Gauntlet audit columns at lines 176–178; no schema/test repair justified.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **1323 reviewed identities, 1323 findings, zero unclassified**, exit 0. No observed unbanked identities; a ledger amendment would be gratuitous.
- Read the frozen issue body (ten acceptance criteria), current profile and schema implementation/tests. The profile explicitly says the runner is a host-process preflight, not the promoted Compose topology. Inspected the captured primary comments (all automated progress notices) and linked PR bodies; these supply no RC artifact/configuration designation.

## Architecture and reconciliation

Read accepted ADR-073126-c4e1 (immutable RC artifacts and promotion), ADR-082526-b36a (executor-owned renewal and reclamation), and ADR-085 (principal rate limits). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and its existing authorities. Admission uniqueness is not physical-work fencing, and a local image build cannot be called the designated release artifact. The production limiter documents an independent budget per process; that does not prove the issue's stronger replica-selection non-bypass criterion. This remains an acceptance gap, not permission to add an authorization authority or silently waive the requirement.

## Additional executed validation

All commands exited zero, with 600/1200-second timeouts:

- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`: **74 passed**. Includes production middleware instances, a real process-group sampler child, negative evidence cases, and host-preflight CLI refusal. Log: `/tmp/860-a656-soak-tests.log`.
- `uv run ruff check .`: passed. Log: `/tmp/860-a656-ruff.log`.
- `uv run ruff format --check .`: 3270 files already formatted. Log: `/tmp/860-a656-format.log`.
- `uv run python scripts/check-suite-inventory.py`: 17 suites match; 31128 unique identities, zero duplicate evidence. Log: `/tmp/860-a656-inventory.log`.
- `uv run python scripts/check-deployment-claims.py`: passed (component/backend existence, not a deployed load proof). Log: `/tmp/860-a656-deployment.log`.

## Acceptance audit against reachable behavior

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative release-candidate workload | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one key and health/task/receipt/metrics traffic; `docs/testing/soak/m3a-load-profile.md:152` names the missing users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background workloads. Applicability must be resolved against a designated RC. |
| At least two application replicas | **UNVERIFIED for the RC.** Fresh tests exercise two real limiter instances in-process, not two deployed application replicas. |
| Sustained saturation, queue, expiry/reclaim, retries and leaks | **UNVERIFIED.** Sampler tests passed but no sustained deployment run was performed. A child allocation test is not a leak soak. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the schedule probe's unexecuted Run through the canonical store. Receipt identity tests do not execute or fence physical effects. |
| Rate/security/degraded concurrency non-bypass | **UNVERIFIED overall; independent replica budgets reproduced.** `tests/test_soak_promotion_gates.py:439` passed for authenticated and unauthenticated identities: the same identity gets 200,200,429 from each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates the local limiter. Backpressure tests passed but do not prove cluster-wide security. |
| Complete telemetry with explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1422` observes driver-loop lag, not application-loop latency. Process sampler coverage passed; no complete RC time series was evaluated. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED.** Boot cleanup and evidence-evaluator tests do not constitute a live physical-work crash/recovery experiment. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730–741` rejects the host-process runner as exact-RC evidence. The four-hour CLI test executed synthetic evidence and proved refusal; it did not run four hours of traffic. No promoted immutable artifact/configuration was designated in the assignment or inspected primary/PR evidence. |
| Findings filed/reclassified before promotion | This report records the current findings; external filing/reclassification **UNVERIFIED**, with GitHub mutations prohibited. Historical schema failure is already repaired at the assigned head. |
| Hash-bound machine/human soak evidence | **UNVERIFIED for the RC.** This source-linked local validation report is not a machine/human exact-RC soak evidence pack. |

## Handoff

**BLOCKED**, not integration/promotion approval. Only this report changed. No test additions or edits, so no inventory delta is needed. No production or ledger change is supported by the reproduced CI evidence; no sync conflict exists. All inherited work is preserved.

Next prerequisite: release-owner designation of the immutable artifact/configuration and workload applicability. Then complete the production-topology runner, physical-effect/recovery oracles and telemetry; resolve the replica-rate-budget requirement; run an unchanged >=14400-second representative multi-replica soak and publish hash-bound results. Replaying the historical schema failure or clean vulture gate cannot resolve these prerequisites.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues; errors 0 validation commands. Local validation/report complete; RC acceptance remains blocked.
