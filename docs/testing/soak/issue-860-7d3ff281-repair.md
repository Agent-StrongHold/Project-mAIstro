# Issue #860 — bounded repair 7d3ff281

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`768a87316d2f330a8731ad74eb9445c3d71c7384`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
No PR processing, GitHub mutation, or develop sync conflict is assigned/present.

Candidate repair surfaces: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
its production implementation `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`quality/vulture-baseline.json` (only if the exact mandated scan shows debt),
an inventory note if tests change, and this report. Read-only supporting
architecture, workflow and deployment files are permitted. Do not broaden to
implement separate rate-limit or durable-receipt authorities.

## Intake evidence / ambiguity

The supplied prior `check-3.log` failed on 24 schema DDL statements versus 21
expected. The supplied prior result reports BLOCKED on missing exact-RC soak
and independently reproduced process-local rate/receipt behavior. These are
historical claims to revalidate, not acceptance evidence for this HEAD.
No `check-*.log` exists in this job directory at intake. Assumption: writer
must execute fresh checks, not infer success from absent driver logs.

## Progress

- Snapshot recorded; starting ref matches dispatch exactly.
- Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** (live PostgreSQL cases skipped). The historical
  24-versus-21 mismatch is already fixed: the test independently lists all 24
  upgrades, including three Gauntlet audit columns. No new repair warranted.
- Exact mandated vulture command: **passed**, 1322 reviewed identities / 1322
  findings, zero unclassified and never-allowlist findings. Workflow arguments
  match `.github/workflows/quality.yml:1079`. No ledger edit warranted.
- Results saved locally to `/tmp/860-7d3-schema.log` and
  `/tmp/860-7d3-vulture.log`. Next: assess production soak gaps and execute
  focused evidence tests, lint and inventory gates.
- `uv run ruff check .`: **passed**; `uv run ruff format --check .`:
  **passed**, 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **73 passed**. Real middleware/production-router ASGI probes reproduce
  separate per-instance allowances and a peer receipt 404; they do not deploy
  two production replicas.
- `uv run python scripts/check-suite-inventory.py`: **passed**, all 17 suites
  match, 31323 unique identities, no copied-test duplication. No tests changed;
  no inventory-delta note required.
- Logs: `/tmp/860-7d3-{lint,format,soak-tests,inventory}.log`.

## Architecture and reachable behavior

Read repository instructions, documentation authority map, accepted
ADR-081226-a66b, ADR-081626-f383, ADR-082426-82c7, and proposed ADR-081.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. A unique admitted Run
is not proof of unique physical work. The accepted lease contract explicitly
excludes implicit expiry takeover; #860 cannot authorize a competing recovery
scheduler. Proposed deployment guidance does not waive the issue's acceptance.

`deploy/docker-compose.prod.yml` declares two application services, a primary
and replica database, Redis, and a shared store. It is a reference build, not
an immutable selected RC. `scripts/soak/run_soak.py:744` correctly reports
`exact_rc_artifact.ok=false` for its host-process preflight. The executed
promotion-gate tests cover rejecting that evidence even at four hours.

Fresh tests execute the real rate-limit middleware (`tests/test_soak_promotion_gates.py:439`):
the same identity receives 200,200,429 on each independent instance, for both
authenticated and unauthenticated cases. This proves local enforcement, not a
shared principal budget. The production task-router probe at line 564 admits
work through the canonical spine, reads its local receipt successfully, and
observes a peer 404. Neither result is a deployed production soak; neither
should be hidden with driver affinity or retries.

## Acceptance assessment

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC users/Workspaces, traffic, fan-out, schedules, tools/models, Design/Canvas and workers | **UNVERIFIED**. Read `m3a-load-profile.md`; it explicitly lists missing representative workloads. No selected RC profile was exercised here. |
| At least two production application replicas | **UNVERIFIED**. Two-instance ASGI probes passed, but no deployed RC replicas were exercised. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff and memory/fd/process leaks | **UNVERIFIED**. No sustained production run executed. |
| No duplicate physical work across schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED**. Admission/harness checks are not physical execution or recovery evidence. |
| Replica-resistant rate/security/degraded enforcement | **NOT PROVEN**. Fresh middleware tests reproduce independent allowances; local 429 behavior cannot establish a cluster-wide limit. Backpressure tests pass, but do not prove this full criterion. |
| Required production telemetry and explicit thresholds | **UNVERIFIED**. Profile has thresholds; no fresh production series. Driver loop lag and SELECT 1 are not application-loop latency or application query/pool telemetry. |
| Active-work kill/restart, graceful drain, fencing and recovery | **UNVERIFIED**. No production restart executed. Exit/rejoin and terminal Run counts are insufficient. |
| Long soak of exact promoted RC artifact/config | **UNVERIFIED**. Executed tests confirm host preflight fails the artifact gate. No exact-RC long soak executed. |
| Load findings classified to earliest broken milestone | **UNVERIFIED** for campaign completeness. Existing limitations retained; no GitHub mutations performed. |
| Machine/human soak evidence bound to image/package/commit/config hashes | **UNVERIFIED** at promotion grade. This report binds local validation to starting source HEAD, not a production image/configuration. |

## Handoff / residual risks

**BLOCKED**, not merge-ready. Only this validation report changed; no observed
CI failure warrants a code, test, gate or ledger edit. The historical schema
failure must not be reused as evidence against this HEAD. No inventory delta
was introduced. Focused tests passed, not the full repository test battery;
six live PostgreSQL cases remain skipped.

Next action requires selecting the immutable RC and runtime configuration,
resolving or explicitly scoping production-path limitations under accepted
architecture, and running the representative, instrumented production soak
(at least four hours per the profile), including physical-work and recovery
observations. Another host preflight or static-check-only repair will not
satisfy those acceptance criteria. No promotion or integration approval is
implied by this checkpoint.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC selection and production soak}. Validation checkpoint complete;
issue acceptance remains blocked. Commit this report locally and leave the
worktree clean.
