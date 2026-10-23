# Issue 860 — bounded repair checkpoint

## Frozen scope

- Sole issue: #860; branch `auto-860`; clean starting HEAD
  `32b8c6b428d8f8753bd3a4d6d0008881b406c702`; supplied base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Inspect the supplied dispatch snapshot, prior result and failure log,
  repository instructions, relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and the load-profile/evidence docs.
- Execute the requested exact vulture gate before deciding on any ledger edit.
  Review only identities actually reported by that invocation.
- Allowed changes: evidence-backed gate repair, associated tests/inventory note
  if needed, and this checkpoint. No unrelated production repair or new
  execution/authorization authority.
- Current job directory has no `check-*.log` files. Prior result is evidence,
  not verification. No uncommitted work needed salvage.

## Ambiguity / assumption

The lane is a writer repair, not the verifier-only role described in the shared
prompt. Treat exact-RC load evidence as required for issue acceptance; unit
checks cannot substitute for it. Do not rerun historical host-process probes
and label them a production soak.

## Results

- Requested exact vulture scan passed: 1,322 reviewed identities and 1,322
  findings, zero unclassified / never-allowlist findings. No ledger edit is
  justified by this scan.
- Supplied historical `98a113.../check-3.log` reports a learnings schema test
  mismatch (24 DDL statements versus 21), not a vulture failure. Current
  schema tests passed; the three audit columns already appear in the expected
  DDL list (`test_pg_learnings.py:173-175`). No repair needed.
- Read the load profile and all adjacent promotion-gate tests. The profile
  explicitly disclaims exact-RC execution and records missing representative
  traffic and telemetry. Tests include contrary evidence for cluster-wide
  rate-budget claims. No completion or promotion claim.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,301 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped. Database skips are not acceptance evidence.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q`: 73 passed. Includes actual production middleware and task router
  calls through ASGI; these are not deployed multi-replica load tests.
- `uv run python scripts/check-suite-inventory.py --suite tests/ --suite
  packages/maistro-core/tests --suite packages/maistro-server/tests`: passed,
  22,218 unique test identities; no duplicate evidence. No tests changed or
  added, so no inventory delta note is needed.

## Architecture reconciliation

Read accepted ADR-081426-1f7c, ADR-081626-f383 and ADR-082126-f69c. Physical
execution identity is Attempt; the canonical Run store owns fencing authority;
recurrence admits Runs rather than creating a second runtime. Therefore a
single admitted schedule Run cannot prove physical-work uniqueness or recovery.
The existing driver cancels that unexecuted Run through the canonical store
(`scripts/soak/run_soak.py:1067-1099`). No architecture changes were made.

The production rate middleware explicitly documents process-local scope
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37`). The
passing independent-allowance regression demonstrates that switching replicas
allows additional requests for the same principal/IP. This is not a new auth
path or proof of cluster-wide enforcement; reconciling the issue's stronger
claim requires production work or an explicit supported-topology decision,
not relabeling the six local rate probes as a shared budget.

## Acceptance accounting

| # | Criterion | Current evidence and disposition |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED: inspected `m3a-load-profile.md`; it explicitly lacks multiple users/Workspaces, successful tool/model work, fan-out and Design/Canvas. No designated RC configuration justifies exclusions. |
| 2 | Two production replicas | UNVERIFIED: `preflight_artifact_check()` identifies host uvicorn rather than the promoted Compose topology. No deployment run executed this round. |
| 3 | Sustained saturation/reclaim/leak observations | UNVERIFIED: no new sustained run; focused tests cannot establish long-window behavior. |
| 4 | No duplicate physical work | UNVERIFIED: the schedule race admits then cancels its unexecuted Run; it cannot observe physical Attempt fencing or Goal reconciliation. |
| 5 | Replica-independent security/rate/degraded enforcement | UNVERIFIED with contrary rate evidence: both parameterizations of `test_replica_selection_has_an_independent_production_allowance` passed, demonstrating fresh allowance on replica 2 after exhausting replica 1. |
| 6 | Complete telemetry with thresholds | UNVERIFIED: profile distinguishes driver loop lag from application loop lag and documents missing production worker, pool saturation and lease-reclaim observations. No fresh production telemetry. |
| 7 | Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: boot cleanup and response accounting tests passed, but no active production Attempt was killed and recovered. |
| 8 | Long-running exact RC/config soak | UNVERIFIED: four-hour-preflight rejection tests passed. `run_soak.py:744-755` always marks this runner's artifact check false; no exact promotion artifact/configuration was designated in the lane. |
| 9 | Findings disposition to earliest broken invariant | UNVERIFIED: this report records observed limitations and contrary evidence, not a complete production findings disposition. No GitHub mutations. |
| 10 | Machine/human evidence bound to promoted hashes | UNVERIFIED: this report records validation of the supplied starting hash, not an exact-RC machine-readable soak pack. |

## Final handoff

**BLOCKED.** The requested CI failure is not current and the exact vulture scan
provides no unbanked identities to amend. Do not manufacture a ledger change or
weaken the artifact gate to turn this into MERGE-READY. Only this checkpoint
changed; all existing source, tests, ledger and evidence are preserved.

Focused validation: 110 passed, 6 skipped; lint, format and inventory passed.
Progress: checked 1 issue, done 0, skipped 0, validation errors 0, blocked 1.
Next: designate immutable RC images/configuration, supply a production-topology
runner and representative workloads through Goal -> Graph -> Run -> NodeRun ->
Attempt, and run the required four-hour soak with physical-work, recovery and
production telemetry observations. Resolve the replica-selection allowance
claim before promotion. This cannot be repaired by another passing scanner run.

