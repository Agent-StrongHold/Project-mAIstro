# Issue #860 — bounded repair validation

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `9dbc6913fb4e379533f30648a674bb370b593d7c` (clean).
- Assigned base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Inspect existing soak implementation, adjacent tests, relevant ADRs, and run the explicitly requested vulture gate plus focused acceptance validation.
- Candidate edits: this handoff; `quality/vulture-baseline.json` only if fresh scanner evidence warrants the explicitly permitted repair. No speculative production or ledger changes.
- Dispatch snapshot: job `8ab0931238ec483496e08294eba9744f`; no GitHub refresh or mutation.
- No `check-*.log` files were present in that job directory at start. Prior result is evidence to recheck, not proof.
- Assumption: this is a writer repair lane. Exact-RC deployment acceptance cannot be inferred from local tests or historical artifacts.

## Progress

- Required vulture command passed: 1322 findings / 1322 reviewed identities, zero unclassified and never-allowlist findings. Log: job-local `worker-vulture.log`. No ledger amendment is warranted.
- Read supplied historical `98a11313/check-3.log`: failure is a schema-test count mismatch (24 DDL statements versus 21), not a vulture finding. Fresh combined focused test run passed: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q` — 109 passed, 6 skipped in 2.02s. Historical failure does not reproduce; skipped integration cases are not live PostgreSQL proof. Log: job-local `worker-focused-tests.log`.
- Read repository instructions and prior handoff. Prior handoff correctly labels its production acceptance unverified; read the full load profile and accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a. The latter extends the earlier lease contract with renewal/reclaim; lack of soak proof must not be described as lack of the mechanism. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. Focused tests passed, but no production deployment or long soak has been executed.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed (3301 files). `uv run python scripts/check-ratchet-provenance.py`: passed (53 consumers; nonfatal invalid-escape SyntaxWarnings). Log: job-local `worker-quality.log`. Gate-selected trusted base is `321cbdb8fe9b`; no provenance overrides used.
- Historical failure is already addressed by the three validation-audit columns listed at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173–175`. Production upgrades remain inside the transaction/advisory fence at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–222`.
- Inspected production `api/rate_limit.py:93` (per-instance `InMemoryRateLimiter`) and `api/tasks.py:144` (injected queue receipt lookup). Initial reads under nonexistent `middleware/` and `routers/` paths returned not found; skipped those paths and used the exact imports from the tests.
- Executed `test_replica_selection_has_an_independent_production_allowance` observes `[200, 200, 429]` on each replica for the same identity, both authenticated and unauthenticated. Executed receipt-router probe observes owner 200 and peer 404. These are ASGI production-component probes, not claims about deployed ingress behavior.
- `scripts/soak/run_soak.py:744–755` deliberately returns `exact_rc_artifact.ok=false`. Executed four-hour CLI tests reject missing, null and preflight artifact records. Extending this emulator's duration cannot establish RC equivalence.

## Acceptance disposition

| Criterion | Fresh evidence / limitation |
|---|---|
| Representative release workload | **UNVERIFIED**: inspected full profile; one identity, degraded model execution, missing concurrent Workspaces, Graph fan-out and successful tool/model/Design/Canvas workloads. |
| Two production replicas | **UNVERIFIED**: two-instance ASGI probes passed, not a deployed topology. |
| Sustained saturation, queue growth, reclaim, retry, leaks | **UNVERIFIED**: no sustained production run executed. |
| No duplicate physical work | **UNVERIFIED**: admission tests do not observe physical Attempt uniqueness; profile's schedule probe cancels its queued Run. |
| Replica-resistant rate/security/degraded enforcement | **UNVERIFIED** for deployment: independent middleware allowances reproduced; local enforcement does not prove a shared principal budget. |
| Complete telemetry and thresholds | **UNVERIFIED**: profile has thresholds, but driver loop/query observations cannot establish application telemetry or detached-worker resource health. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED**: no active physical Attempt fault injection executed. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED / BLOCKED**: existing runner fails artifact equivalence by design; no immutable RC image/configuration selected in the lane brief or exercised here. |
| Findings filed/reclassified before promotion | **UNVERIFIED** for completeness: local findings retained; GitHub mutations prohibited and not performed. |
| Machine/human evidence bound to exact hashes | **UNVERIFIED** for promotion: this source-bound validation note and job logs are not an image/package/config-bound production soak pack. |

## Handoff

**BLOCKED**. No scanner debt or reproducible historical CI failure warrants a
repair. Only this report changed; no production, test, inventory or ledger edits.
No tests were added, so no inventory delta is needed. Do not retry this lane on
the same deterministic results expecting production acceptance to change.

Next prerequisite: release-owner-selected immutable RC image/configuration and
representative workload, with application telemetry and an execution environment
for the profile's >=4-hour soak. Prove physical Attempt failure/recovery and
replica-resistant enforcement through canonical owners, not a parallel scheduler,
store or authorization path. Any code/runtime-config repair then requires a new
soak. Existing CI success does not discharge these prerequisites.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production acceptance evidence}.
Local commit required; no push, PR, closure or integration approval.
