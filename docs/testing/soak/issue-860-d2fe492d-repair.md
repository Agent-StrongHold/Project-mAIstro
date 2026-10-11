# Issue #860 repair — d2fe492d

## Frozen scope

Only issue #860, branch `auto-860`, starting at
`d8cc70d4388cf6ff6e6eb7eccd77032ea8cdd768`, supplied develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2`.
Initial worktree was clean; no incoming edits to salvage.

Process the supplied schema-fence failure, exact Vulture CI gate, and existing
soak acceptance checks. Candidate edit paths are
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`quality/vulture-baseline.json` (only if actual scan requires it), and this report.
No unrelated issue, PR, grant, or deployment change is in scope.

## Initial evidence and assumptions

- Supplied `98a11313167b41a98a420abfda80c292/check-3.log` reports 24 DDL
  statements against 21 expected statements. Reproduce before changing tests.
- No `check-*.log` files were present in this job directory at initial listing.
- Supplied prior result is BLOCKED, not promotion evidence.
- Exact RC artifact/runtime configuration is not designated in the assignment.
  Local checks can validate harness behavior but cannot certify that RC.
- No sync conflict or dirty files were present. No merge is justified by the
  supplied failure.

## Fresh validation checkpoint

- Exact requested Vulture command passed: 1323 findings / 1323 reviewed
  identities, 0 unclassified, 0 never_allowlist (selected base `4aa68edc0b6b`).
  No unbanked identities exist to amend; changing the ledger would be cosmetic.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **103 passed, 6 skipped** in 3.26s. Supplied failure did not reproduce.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files formatted.

The schema test already independently expects the three Gauntlet upgrade
columns (`test_pg_learnings.py:171–175`), unlike the supplied failing log.
Existing meaningful regression tests were executed, not added or weakened;
there is no inventory delta in this round.

Read accepted ADR-081226-69ee, ADR-081626-f383 and ADR-085. Canonical execution
and security authorities are unchanged. In particular the accepted lease ADR
explicitly does not define expiry takeover; the issue cannot authorize a
competing reclaim scheduler. Passing per-principal local rate tests does not
establish distributed enforcement.

## Additional gates

All exited 0:

- `uv run python scripts/check-deployment-claims.py` (existence check only).
- `uv run python scripts/check-merge-markers.py`.
- `uv run python scripts/check-backlog-consistency.py` (168 items).
- `git diff --check`.

## Acceptance review

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:151–170` explicitly identifies missing users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and background workloads. |
| Two application replicas | UNVERIFIED for the RC. Executed tests instantiate two production middleware instances, not two deployed application replicas. |
| Sustained load observing saturation, queues, leases, retries and leaks | UNVERIFIED. Focused tests are not a sustained deployment run; the accepted lease contract also limits reclaim claims. |
| No duplicate physical work across replicas | UNVERIFIED. Admission checks are not proof of physical Attempt uniqueness or Goal reconciliation under load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT PROVEN. Executed `tests/test_soak_promotion_gates.py:439` reproduces 200,200,429 independently on both instances for the same identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs an in-memory limiter, installed at `main.py:648`. Router backpressure regressions pass, but are not a distributed security proof. |
| Full PostgreSQL/application/worker telemetry with thresholds | UNVERIFIED. No fresh RC telemetry. The profile distinguishes driver-loop measurements from application-loop measurements and lists remaining instrumentation gaps. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. No deployed active-work fault injection was executed. |
| Long-running soak of exact RC/configuration | BLOCKED / UNVERIFIED. Assignment does not designate immutable RC images and runtime configuration. `scripts/soak/run_soak.py:730` always returns failed artifact evidence for host-process preflight; executed promotion-gate regressions enforce this. A longer preflight is not a substitute. |
| Findings filed/reclassified before promotion | UNVERIFIED externally. Current discrepancies recorded locally; no GitHub mutations or new load run performed. |
| Machine/human evidence tied to exact artifact/configuration | UNVERIFIED for RC. This report and test output concern the source checkout, not a deployed promotion artifact. |

## Disposition and handoff

**BLOCKED.** The supplied schema failure is stale for the assigned HEAD and the
requested Vulture gate already passes. No production/test/ledger/gate edits are
justified by fresh results. Only this report changed; existing work is preserved.
Six skipped tests do not count as live PostgreSQL evidence. Focused passing tests
do not certify the accumulated branch or close the issue.

Required next inputs/work: designate immutable RC images and runtime
configuration, complete representative production workloads and telemetry,
resolve the replica-selection rate scope discrepancy through canonical security,
then run the long exact-artifact soak including active-work recovery. Any code or
runtime-config change requires another soak. Artifact designation remains
UNRESOLVED; repeating the supplied stale CI repair will not resolve acceptance.

No tests were added, so no inventory note or count update is needed. No remote
mutation, push, merge, grant change, or competing execution authority was made.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
Local report commit is the checkpoint for this bounded repair attempt.
