# Issue #860 repair checkpoint — 4f9e804f

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD `7ba46dda3cd162acaae3653a7af71a9ea8a20a50`, supplied base `2154f845347c9541016288c760f8da3f5cd2e064`.
- Worktree initially clean; no incoming uncommitted work to salvage.
- Process only the supplied schema-fence failure and exact-debt-ledger repair, then assess the ten acceptance criteria. No linked PR/issue processing or GitHub mutations.
- Candidate edit surfaces: this checkpoint; `packages/maistro-core/tests/persistence/test_pg_learnings.py`; `packages/maistro-core/src/maistro/persistence/pg_learnings.py` if actual reproduction warrants it; `quality/vulture-baseline.json` for observed reviewed identities only; `docs/testing/inventory-notes/860-4f9e804f-repair.md` if tests change. Other production changes require a new assignment, not speculative expansion.
- Read-only acceptance surfaces: `scripts/soak/`, adjacent soak tests, production topology and relevant ADRs.

## Initial evidence and assumptions

The current job directory contains no `check-*.log` files. The supplied previous `98a113.../check-3.log` reports 24 schema statements versus 21 expected. The supplied prior result is BLOCKED, not release evidence. Assume the writer role explicitly assigned here; do not treat historical soak claims as current verification. Exact RC promotion requires actual deployed workload evidence, not passing unit tests.

## Reproduced CI results

- Required exact command `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,323 reviewed identities / 1,323 findings, zero unclassified or forbidden identities. No evidence warrants a ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: PASS, 37 passed / 6 skipped. The historical 21-versus-24 failure is already repaired: the independent expected DDL includes all three Gauntlet audit columns. No speculative test or production change warranted.
- Missing read-only paths `docs/testing/soak/README.md` and `docs/testing/soak/profile*`: not found; skipped. Locate the actual tracked profile once instead.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,277 files).
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS (72 tests). Includes actual production limiter instances reproducing independent allowances for the same authenticated/unauthenticated identity on different replicas; this is not deployed-load evidence.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items), not proof all load findings have been discovered/classified.
- Requested historical note `docs/testing/soak/issue-860-72a1fe8b-repair.md`: not found; skipped. The supplied result JSON was read successfully instead.

## Acceptance checkpoint

Read the actual profile `docs/testing/soak/m3a-load-profile.md` and production middleware. The profile expressly excludes full Workspace/user populations, successful tools/models, Graph fan-out, Design/Canvas, and Goal reconciliation. `preflight_artifact_check` unconditionally rejects host processes as exact-RC evidence. The schedule probe cancels admitted Runs without execution. The existing production-middleware test freshly demonstrates that exhausting replica 1 does not exhaust replica 2. These are remaining acceptance blockers, not a reason to fabricate a ledger repair or weaken a gate.

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/Node), ADR-081226-a66b (Run/NodeRun/Attempt), ADR-081626-f383 (Attempt leases/fencing), ADR-082126-f69c (recurrence admits Runs), and ADR-085 (principal rate limits). Admission identities do not prove physical Attempt exclusivity. A soak must observe the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` path; adding a private scheduler or independent authorization/store authority is not a valid repair. ADR-085 requires principal-keyed limits but does not specify a cluster-wide mechanism. The production limiter explicitly documents process-local state; BACKLOG.md:267-279 already classifies the stronger #860 non-bypass requirement as `engine-116`, `gap-spec`. This round neither waives that acceptance criterion nor invents a new architecture.

## Final acceptance matrix

| # | Criterion | Fresh evidence and disposition |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED. Read profile: one API key, degraded model calls, no representative Workspace population, Graph fan-out, Design/Canvas or sustained Goal workload. |
| 2 | At least two deployed application replicas | UNVERIFIED. Read production Compose defining two replicas, but did not deploy an exact RC or treat ASGI instances as deployed replicas. |
| 3 | Sustained saturation, queues, reclaim, retries, leaks | UNVERIFIED. No long-running exact-RC workload executed; unit sampler tests are not sustained observations. |
| 4 | No duplicate physical work; Goal reconciliation | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels an admission-only probe without executing its Run; receipt/row uniqueness is not physical-work evidence. |
| 5 | Concurrency security/degradation; no replica-selection bypass | UNVERIFIED at production-soak grade, with a reproduced counterexample to a shared principal allowance: `tests/test_soak_promotion_gates.py:439` uses production middleware; same identity receives two accepted requests then 429 independently on both instances. Both authentication variants passed in the executed 72-test suite. |
| 6 | Complete telemetry and explicit thresholds | UNVERIFIED. Profile captures driver loop lag, not application loop latency; current tests establish sampler behavior, not all requested production telemetry. |
| 7 | Kill/restart during active physical work; drain/fencing/recovery | UNVERIFIED. No deployed active-work kill/restart in this round; process exit/rejoin alone cannot establish no lost/duplicate work. |
| 8 | Long-running soak of exact RC/config; rerun after changes | UNVERIFIED. `scripts/soak/run_soak.py:744` unconditionally returns failed exact-artifact check. Executed tests prove even synthetic four-hour preflight evidence exits unsuccessfully without exact-RC evidence. |
| 9 | Findings classified to earliest invariant | PARTIAL: existing `engine-116` records the rate-budget gap and backlog consistency passes. Completeness and earliest-milestone classification of every load finding remain UNVERIFIED without the workload. No GitHub mutations. |
| 10 | Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED. No new production evidence published; source/host preflight hashes cannot substitute for promoted image/config identities. |

## Outcome and handoff

BLOCKED for #860 acceptance. The supplied schema-test failure and unbanked-vulture concern are resolved in the starting tree, verified afresh rather than assumed. No production/test/ledger changes are justified by those reports. Only this validation handoff changes; no tests were added, so no inventory delta note is needed.

`git diff --check` passed. No full-tree pytest was run (focused scope only); the six skipped PostgreSQL cases are explicitly not database validation. All validation commands used long timeouts (1,200 seconds for validation batches).

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0 issues; validation errors 0. Next: resolve the already-classified cluster-budget contract through its owner and provide a selected immutable RC/config with a production-path workload/telemetry runner; execute the >=4-hour soak including active-work failure/recovery before promotion. Do not repeat ledger edits or cosmetic repairs against already-passing CI.

