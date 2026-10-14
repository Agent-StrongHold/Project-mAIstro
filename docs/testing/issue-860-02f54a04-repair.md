# Issue #860 — bounded repair 02f54a04

## Frozen scope

- Issue #860 only; starting HEAD `ae9ed233e3a26bdafbca19cd0ddabe89034958b2`, assigned base `2154f845347c9541016288c760f8da3f5cd2e064`.
- Clean assigned worktree at start; no salvage required.
- Candidate edits: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, `docs/testing/inventory-notes/860-02f54a04-schema-fence.md`, `quality/vulture-baseline.json` only if the mandated scan identifies reviewed retained debt, and this report.
- Read-only inspection: repository instructions, relevant ADRs, learning persistence/schema and adjacent tests, existing soak runner/profile/tests, CI gate implementation/workflow, supplied dispatch and prior result/log.
- No PR processing or GitHub mutations. No new execution or authorization authority.

## Initial evidence and assumptions

The supplied prior `check-3.log` reports a schema-fence assertion of 21 statements against 24 actual statements. This must be reproduced before changing expectations. The previous result is BLOCKED on missing exact-RC production soak and replica-local rate allowances; it is evidence to recheck, not proof of current acceptance. No current driver `check-*.log` files were present in the supplied job directory at startup. This is a writer/CI-repair round, not a verifier-only round.

## Results

- Fresh exact vulture command passed: 1323 findings / 1323 reviewed identities, zero unclassified or never-allowlist findings. No ledger amendment is justified.
- Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed: 37 passed, 6 skipped (live PostgreSQL tests). The historical 24-versus-21 failure does not reproduce: the expected DDL already includes all three Gauntlet audit columns. No test repair is justified.
- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 73 passed.
- `uv run python scripts/check-deployment-claims.py`: passed (static claims only).
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified / 19 discovered.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.

Validation used 600–1200 second timeouts. No full-tree pytest, deployment or sustained soak was run. A read of `scripts/soak/m3a-load-profile.md` was not found; skipped that path and resolved the profile to `docs/testing/soak/m3a-load-profile.md`. No unresolved ref was executed.

## Architecture and reachable behavior

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (lease fencing), ADR-082526-b36a (renewal/reclaim), ADR-082826-08f0 (shared recovery disposition), and ADR-085 (per-principal limits). The later accepted recovery decisions extend the earlier fencing ADR: reclaim is not deferred, and a live leased Attempt must not be stolen. Admission-only probes cannot establish physical-work recovery. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt; no authority or policy change is made here.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` fences the DDL with a transaction and advisory lock. The passing test independently expects the Gauntlet columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`.
- `packages/maistro-server/src/maistro_server/main.py:648` installs `RateLimitMiddleware`; `api/rate_limit.py:93` constructs its process-local limiter. Executed regression `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` separately from each of two instances, for the same authenticated or unauthenticated identity. This is a production middleware seam, not a deployed multi-replica soak. It falsifies shared allowance without claiming broader security failure.
- `scripts/soak/run_soak.py:744` explicitly refuses exact-RC certification for host-process preflight. Executed CLI regression `tests/test_soak_promotion_gates.py:103` rejects otherwise-passing synthetic four-hour evidence with absent/null/preflight artifact records.
- `scripts/soak/run_soak.py:1067` cancels the schedule probe's unexecuted Run through the canonical store. This tests admission, not physical work.
- `deploy/docker-compose.prod.yml:11` describes a reference artifact needing image digest pinning; it does not designate the immutable artifact/configuration that #89 will promote.
- `BACKLOG.md:267` already records engine-116 (`gap-spec`), the cluster-wide budget blocker. ADR-085's per-principal rule does not supply a cluster-wide implementation decision. No guessed shared-store implementation is introduced in a bounded CI-repair round.

## Acceptance matrix

| # | Criterion | Fresh evidence / disposition |
|---|---|---|
| 1 | Representative RC users/Workspaces, mix, fan-out, schedules, queue, tools/models, Design/Canvas, background work | UNVERIFIED. Read profile explicitly omits multiple required surfaces and uses one API key; no selected RC coverage justification supplied. |
| 2 | At least two deployed application replicas | UNVERIFIED. Two middleware instances are not deployed replicas; Compose definitions are static. |
| 3 | Sustained saturation, queue growth, reclaim, retries, leaks, restart | UNVERIFIED. Bounded tests passed but no sustained production window ran. |
| 4 | Schedule/task/Run/Attempt/Goal uniqueness and physical-work fencing | UNVERIFIED. Admission probe cancels an unexecuted Run; it cannot establish no duplicated physical work or Goal reconciliation under load. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT SATISFIED at the limiter seam: executed two-instance regression reproduces independent allowance. Deployed security/degraded behavior remains UNVERIFIED. |
| 6 | PostgreSQL usage/query latency/locks, application-loop latency, workers/processes/RSS/descriptors/queues/errors/timeouts with thresholds | UNVERIFIED. No fresh telemetry series; the profile distinguishes driver-loop lag from missing application-loop evidence. |
| 7 | Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. No active physical Attempt restart was executed; health rejoin would not prove this. |
| 8 | Long soak of exact RC artifact/config, rerun after changes | UNVERIFIED. Existing preflight correctly refuses artifact certification; no designated immutable RC or four-hour production run established. |
| 9 | Findings classified to earliest broken invariant | Partial: engine-116 is already recorded and backlog gate passes. Completeness remains UNVERIFIED without representative load; no GitHub mutation performed. |
| 10 | Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED. This validation note identifies source HEAD, not a production RC evidence pack. |

## Disposition and next actions

BLOCKED for issue acceptance; the supplied CI failure is stale, and no unbanked vulture debt exists. Only this report changes. No tests added or changed, no inventory count delta, so no inventory note required. No ledger, grant, gate, production code or inherited work altered. No sync conflict exists to resolve.

Next: designate immutable RC/config and representative coverage; resolve engine-116 through the existing limiter seam after its shared-budget contract is decided; run at least the profile's four-hour exact-artifact soak with application telemetry, active physical work, kill/restart, reclaim and stale-writer evidence. Repeating the already-passing schema or vulture check cannot close these acceptance gaps.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues, errors 0 validation commands; next: RC prerequisites and production soak. Local validation handoff only, never integration approval.
