# Issue #860 — a14050cb repair checkpoint

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `3676871f52ef14a85a74fe06106d87c4e0876f0b`, supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2` (both resolved locally).
- Working tree initially clean; no incoming edits to salvage.
- Repair targets: `packages/maistro-core/tests/persistence/test_pg_learnings.py`
  and its production schema implementation for the reported fence mismatch;
  `quality/vulture-baseline.json` only if the exact requested scan supplies
  reviewed evidence; this report and a matching inventory note if needed.
- Acceptance inspection only: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, relevant ADRs and existing load profile.
  No other issues/PRs, remote mutations, authority changes or grant edits.
- No current-job `check-*.log` files were present at initial snapshot.
  Supplied prior `98a113.../check-3.log` reports 24 DDL calls versus 21 expected.
  Prior `0463f353.../result.json` reports BLOCKED, not promotion proof.

## Assumptions

This is a writer/CI-repair round. The acceptance exercise may remain blocked
without a designated exact RC/configuration; passing local tests cannot replace
that evidence. Existing branch history is preserved, including unrelated-looking
base differences; no attempt will be made to erase or reconcile them speculatively.

## Results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The supplied old failure is not reproducible: the
  current expected DDL already includes all three Gauntlet audit columns
  (lines 171–175). No speculative test or production change is warranted.
- Exact requested vulture command: **passed**, 1323 reviewed identities /
  1323 findings, zero unclassified and zero never-allowlist findings. There
  are no unbanked identities to amend; the ledger is deliberately unchanged.
- Read the frozen issue body and latest captured comments. All ten acceptance
  criteria concern observed promotion behavior, not merely unit tests.
- Inspected the driver, load profile and adjacent promotion tests. The profile
  explicitly excludes required representative workloads and calls the driver a
  host-process preflight. Exact-RC acceptance is still a real prerequisite,
  not something to bypass by extending this emulator's duration.
- A lookup at `maistro_server/middleware/rate_limit.py` returned not found;
  corrected to the concrete import in the inspected test,
  `maistro_server/api/rate_limit.py` (no command executed against a guessed ref).
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed**. This includes real production middleware exercised via ASGI,
  fail-closed exact-artifact CLI checks, and task admission backpressure tests.
  It is not a deployed multi-replica soak.
- `uv run python scripts/check-merge-markers.py`: **passed**.
- `uv run python scripts/check-backlog-consistency.py`: **passed**, 168 items.
- `uv run python scripts/check-deployment-claims.py`: **passed** (component
  existence only, not runtime deployment or recovery proof).
- `git diff --check`: **passed**.

## Architecture and acceptance reconciliation

Read `AGENTS.md`, `docs/README.md`, accepted ADR-081226-69ee (Graph/Node
execution), ADR-081626-f383 (canonical Attempt fencing), ADR-085 (per-principal
rate limiting), and ADR-081 (deployment; **Proposed**, not Accepted).
`Goal -> Graph -> Run -> NodeRun -> Attempt` remains authoritative. No new
scheduler, execution authority, state store or authorization path is introduced.
The accepted fencing ADR explicitly does not itself define lease-expiry takeover;
a one-occurrence admission race cannot substitute for proving supported reclaim
behavior. The deployment profile's reference to proposed ADR-081 does not make
it an accepted override of the issue's evidence requirements.

ADR-085 requires principal-keyed limits but does not establish a shared replica
budget. The existing middleware explicitly advertises process-local limits
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:32`) and constructs
an `InMemoryRateLimiter` per middleware instance (line 94). The executed test
`test_replica_selection_has_an_independent_production_allowance` (both auth
variants, `tests/test_soak_promotion_gates.py:439`) observes `[200, 200, 429]`
on each replica for the same identity after exhausting the first. Thus local
429 enforcement is proven, but a strict replica-selection non-bypass claim is
falsified. This round does not silently reinterpret that acceptance criterion
or introduce a new distributed authorization mechanism.

## Acceptance matrix (freshly inspected, not carried forward as passes)

| # | Criterion | Evidence / disposition |
|---|---|---|
| 1 | Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:151` names missing multi-user/Workspace, fan-out, successful tool/model, Design/Canvas and background/Goal workloads. No selected RC configuration supplied to establish applicability. |
| 2 | At least two deployed application replicas | **UNVERIFIED this round**. ASGI middleware instances are not deployed RC replicas; profile lines 16–24 identifies the host-process emulator. |
| 3 | Sustained saturation, queues, leases, retries, leaks and restart | **UNVERIFIED**. No long-running production load executed. Unit sampler and accounting tests passing cannot establish these observations. |
| 4 | No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. Admission identity tests pass; profile lines 199–204 explicitly says the claim probe cancels its Run without execution and does not prove physical Attempt fencing. |
| 5 | Concurrent rate/security/degraded non-bypass | **NOT PROVEN**. Production-middleware tests pass for local 429 enforcement and demonstrate independent replica budgets; no cluster non-bypass proof or sustained deployed security exercise. |
| 6 | All required telemetry with pass/fail thresholds | **UNVERIFIED at RC grade**. Sampler tests pass, but profile lines 163–168 distinguish driver loop lag from application loop lag and acknowledge missing worker/saturation/reclaim observations. |
| 7 | Active-work kill/restart drain/fencing/recovery | **UNVERIFIED**. Cleanup tests pass, not active-work recovery proof. Exit/rejoin and terminal row counts are insufficient. |
| 8 | Long soak of exact promoted artifact/configuration | **BLOCKED**. `run_soak.py:730–741` returns `exact_rc_artifact.ok=false`; three passing CLI regressions reject otherwise-passing four-hour preflight evidence. No designated immutable RC image/configuration was supplied. |
| 9 | Load findings filed/reclassified before promotion | **UNVERIFIED for final promotion**. Existing reports classify preflight findings, but no fresh load findings or external filing performed; GitHub mutations prohibited. Replica budget issue recorded locally above. |
| 10 | Machine/human evidence tied to exact hashes | **UNVERIFIED for RC**. This local report records validation; historical preflight bundles cannot certify an unselected RC and are not re-labelled as current evidence. |

## Handoff

Only this report changed. No test additions or count changes, hence no inventory
delta note; no unbanked findings, hence no ledger amendment. The old deterministic
failure is already repaired, and the required exact-debt scan is green. An
additional cosmetic repair would not resolve the remaining acceptance failures.
The starting branch also has a substantial accumulated diff relative to the
supplied base, including removals outside #860; it was preserved and is not
certified by this focused round.

**Verdict: BLOCKED, not integration approval.** Next action requires an explicitly
designated immutable RC/configuration and a production-topology workload covering
the missing surfaces, plus resolution of the strict replica-budget requirement.
Run the long soak only after those prerequisites are established; any runtime
change invalidates previous soak evidence. Do not repeat the host emulator or
edit the ledger to manufacture a promotion pass.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC selection and acceptance prerequisites"}`.
The one assigned issue has been checked; its acceptance is blocked. Focused
validation is complete, with results preserved for local commit.

