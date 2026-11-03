# Issue #860 — bounded repair validation (059c37ae)

## Frozen scope

- Issue #860 only; assigned branch `auto-860`, starting HEAD
  `eedd9dcdaf481334f40b1a2954f782ed362ddaed`, base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
- Process the supplied schema-fence failure and required exact vulture scan,
  then assess the ten issue acceptance criteria against the existing harness.
- Candidate implementation files: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `quality/vulture-baseline.json` (only reviewed scan findings), this report,
  and `docs/testing/inventory-notes/m3a-860-059c37ae.md` if tests change.
  Adjacent architecture, tests, ADRs and CI definitions are read-only context.
- No GitHub mutation, new execution authority, or invented RC identity.

## Initial evidence and ambiguity

The job directory contains no `check-*.log` files. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports a schema-fence test
expecting 21 DDL statements while production executed 24. This is historical
failure evidence, not proof it still fails. Reproduce before repairing.
The supplied prior result says BLOCKED on production soak acceptance. Treat
that as a hypothesis to verify, not authority to claim completion.

## Reproduced results

- Required exact vulture command: PASS, 1323 reviewed identities / 1323
  findings, zero unclassified or never-allowlist findings. No ledger amendment
  warranted; no guessed scanner repair.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped. The historical failure does not reproduce.
  Current test independently expects all 24 DDL statements, including the
  three Gauntlet audit columns at lines 177–182; production executes them
  inside its transaction-scoped advisory lock. No schema repair warranted.

## Additional executed validation

All validation used 1200-second command timeouts in the assigned worktree.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_prod_stack_boot_contract.py -x -q`:
  PASS, 74 passed. Together with learning-store tests: 111 passed / 6 skipped.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique identities, no duplicate evidence. No tests added or changed;
  no inventory delta required.
- Executed a Python import of `scripts/soak/run_soak.py` and evaluated
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`. Asserted failures
  exactly `sustain_duration` and `exact_rc_artifact`: PASS. Recorded duration
  is 420.08 seconds versus the required 14400 seconds. Also asserted the
  current `preflight_artifact_check()['ok']` is false. This is an evaluation
  of historical evidence, not a new deployment or soak.

## Architecture reconciliation

Read repository instructions, the documentation authority map, accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082126-f69c, and ADR-082526-b36a.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and canonical recurrence
admission. No implementation authority changes are made.

**Correction to the supplied prior handoff:** ADR-081626-f383's original
boundary is not the last word on reclaim. Accepted ADR-082526-b36a explicitly
adds fenced renewal and expiry reclamation through the canonical store and
AttemptExecutionService. A representative soak should exercise that existing
contract, not invent a second scheduler or treat reclaim as architecturally
forbidden. This does not establish that reclaim was exercised under load.

## Acceptance matrix

| # | Criterion | Evidence and disposition |
| --- | --- | --- |
| 1 | Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:152` identifies missing concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background workloads. Read the profile and executable request paths; unit tests do not fill these gaps. |
| 2 | At least two deployed application RC replicas | **UNVERIFIED.** Boot-contract tests pass; no immutable production RC deployment was designated or exercised this round. Host processes/ASGI instances are not that evidence. |
| 3 | Sustained saturation, queue growth, reclaim, retries, leaks and shutdown | **UNVERIFIED.** Historical evidence fails duration; process-sampler tests pass but cannot establish long-window behavior. |
| 4 | No duplicate physical work across admission/schedules/Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without executing it. Tested admission identities cannot establish physical Attempt uniqueness or Goal reconciliation. |
| 5 | Rate/security/degraded behavior not bypassable by replica selection | **UNVERIFIED overall; contrary allowance evidence reproduced.** `tests/test_soak_promotion_gates.py:439` executes production middleware for both authentication classes and observes `[200, 200, 429]` independently on each instance for the same identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents process-local policy. Local rejection is not a shared budget. |
| 6 | Complete telemetry with explicit thresholds | **UNVERIFIED.** Profile distinguishes driver-loop latency from application-loop latency and SELECT 1 wire latency from application query latency. No fresh long-window RC telemetry collected. |
| 7 | Kill/restart during active physical work; drain/fencing/recovery | **UNVERIFIED.** Boot cleanup and evidence-gate regression tests pass, not a deployed active-work recovery experiment. |
| 8 | Long-running unchanged exact RC artifact/configuration | **UNVERIFIED / BLOCKED.** Current host runner emits `exact_rc_artifact.ok=false` at `scripts/soak/run_soak.py:730`; historical evidence fails artifact and duration checks. Four-hour synthetic evaluator tests prove fail-closed behavior only. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED externally.** Gaps recorded here; no GitHub mutation authorized or performed. |
| 10 | Published machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED.** Historical preflight JSON/docs are not current immutable RC proof. |

## Disposition

**BLOCKED.** Historical CI failure is stale and the required exact vulture scan
has no unbanked identities. No evidence warrants production, test or ledger
changes. Only this report changes; commit locally, never push.

Next: designate the immutable RC image/configuration and complete the
production-topology workload/telemetry runner, reconcile the process-local
rate policy with replica-selection acceptance, then run active-work recovery
and at least four hours of unchanged exact-RC load. Repeating this bounded
CI round cannot satisfy those prerequisites. No develop-sync conflict was
present; no fetch, merge, ref deletion or destructive command was used.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`.
Here done means issue acceptance completed; this bounded validation is complete.
