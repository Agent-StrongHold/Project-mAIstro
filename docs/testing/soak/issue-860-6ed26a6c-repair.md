# Issue #860 repair — 6ed26a6c

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `becee12d4ab31e4dcc52303a45ffd51d76a1f634`.
- Supplied develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Worktree was clean on entry; no incoming edits to salvage.
- Process the supplied dispatch snapshot and prior failure, without refreshing GitHub.
- Inspect existing soak implementation, adjacent tests, governance, and exact vulture gate. Amend production/test files only for reproduced defects; permitted ledger changes only for reviewed identities.
- This note is the progress checkpoint. No remote mutations or integration approval.

## Initial evidence

The supplied previous result reports BLOCKED: local checks passed, but a deployed representative exact-RC multi-replica soak was not established, and independent per-replica rate allowances were reproduced. Those claims require fresh verification. No `check-*.log` files are present in the current job directory at entry; inspect the explicitly supplied prior failure log instead.

## Results

Fresh focused validation:

- Requested exact Vulture command passed: 1323 findings, 1323 reviewed identities, zero unclassified and zero never_allowlist; selected base `4aa68edc0b6b`. There are no unbanked identities to amend.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 103 passed, 6 skipped in 2.44s. The supplied 24-versus-21 schema failure did not reproduce.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3270 files).

The load profile explicitly identifies remaining representative-workload and telemetry gaps. The assignment does not designate immutable RC images/runtime configuration; assume this remains a required external input, not permission to certify a substitute preflight. No sync conflict is present. The acceptance review below distinguishes existing local regressions from deployed proof.

## Architecture and failure review

Read repository `AGENTS.md` and accepted ADR-081226-69ee, ADR-081626-f383, and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and existing canonical security. The lease ADR explicitly does not define expiry takeover; #860 must not invent a reclaim authority to satisfy its wording. Per-principal rate identity is not proof of a shared distributed allowance.

The supplied prior `check-3.log` expected 21 schema statements but observed 24. The current independent expectation already includes all three Gauntlet audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`. Production `ensure_schema` takes the advisory lock inside the transaction before all upgrades (`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`). The existing regression passed freshly; no test weakening or schema edit is warranted.

Additional commands all exited 0:

- `uv run python scripts/check-deployment-claims.py` (component existence only, not live deployment proof).
- `uv run python scripts/check-merge-markers.py`.
- `uv run python scripts/check-backlog-consistency.py` (168 items).
- `git diff --check`.

## Acceptance evidence

| #860 acceptance criterion | Fresh evidence and remaining disposition |
| --- | --- |
| Representative supported RC load profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:151–170` acknowledges missing users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background-worker workloads. |
| At least two deployed application replicas | UNVERIFIED for an exact RC. Executed tests instantiate two production middleware instances, not deployed application replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, memory/descriptor/process leaks and shutdown | UNVERIFIED. Focused regressions are not sustained load; reclaim claims also require reconciliation with the accepted lease ADR. |
| No duplicate physical work across schedules/task/Run/Attempt/Goal reconciliation | UNVERIFIED. Admission evidence is not physical-work uniqueness; profile lines 193–203 acknowledge the schedule probe does not execute its Run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT PROVEN. Executed `tests/test_soak_promotion_gates.py:439` produces 200,200,429 independently on each instance for the same identity, both authenticated and unauthenticated. Production constructs `InMemoryRateLimiter` at `packages/maistro-server/src/maistro_server/api/rate_limit.py:93`, installed at `main.py:648`. Existing process-local semantics do not establish this issue's non-bypass criterion. Backpressure regressions pass but are not a distributed security proof. |
| Complete PostgreSQL/application/worker telemetry with pass/fail thresholds | UNVERIFIED. No new RC telemetry. Driver-loop lag is not application-loop lag; profile lines 151–170 retain instrumentation gaps. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. No deployed active-work fault injection in this round; process exit/rejoin alone is insufficient. |
| Long-running soak of exact RC artifact/configuration, rerun after changes | BLOCKED / UNVERIFIED. No immutable RC images/runtime configuration designated in the assignment. `scripts/soak/run_soak.py:730` deliberately fails artifact certification for host-process preflight; executed promotion-gate tests protect that distinction. |
| Load findings filed/reclassified before promotion | UNVERIFIED externally. Local findings recorded here; no GitHub mutation and no new load run. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for RC. This note binds focused source-checkout checks only, not deployed promotion artifacts. |

## Handoff

**BLOCKED.** Fresh checks confirm the supplied gate failure is stale for this HEAD. Vulture has no unbanked findings, so amending its ledger would be cosmetic. No production, tests, ledger, grants, or gates changed; only this report changed. No tests were added, so no inventory delta is needed. The six skipped tests are not live PostgreSQL evidence.

Required next inputs: designate the immutable RC images and complete runtime configuration; complete representative workloads and missing telemetry; resolve replica-selection rate semantics through canonical security; execute the long-running exact-artifact soak with active-work recovery and physical-work observation. Artifact designation remains UNRESOLVED. Repeating this same stale CI-repair assignment cannot supply that evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`. Local report commit is this bounded attempt's checkpoint, not integration approval. No remote mutation, merge, push, or issue closure.
