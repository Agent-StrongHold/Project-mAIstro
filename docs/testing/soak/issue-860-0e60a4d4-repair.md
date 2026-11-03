# Issue #860 — focused repair checkpoint

## Frozen scope

- Issue: #860 only; branch `auto-860` in assigned worktree.
- Starting HEAD: `90a5362ec7a410f667f8516b4c9bef0eea0fefed`.
- Develop base: `34795962548a33f6b6f7e1234dcea201a9df96ef` (resolved locally).
- Clean incoming worktree; no salvage required.
- Files in repair scope: this report; `quality/vulture-baseline.json` only if the mandated scan finds reviewed retained identities; `packages/maistro-core/tests/persistence/test_pg_learnings.py` and its production `pg_learnings.py` only if the reported failure reproduces; `tests/test_soak_promotion_gates.py`, `scripts/soak/run_soak.py`, and `docs/testing/soak/m3a-load-profile.md` for acceptance inspection; an inventory note only if tests change. Adjacent architecture, repository instructions, existing evidence and tests are read-only context.
- No GitHub operations, promotion, or new execution authority.

## Initial evidence / ambiguity

Current job directory contains no `check-*.log`. The supplied prior `check-3.log` reports a schema-fence test expecting 21 statements but receiving 24. The prior result is BLOCKED with production soak criteria unverified; these claims are not assumed correct. Proceed with fresh focused checks, not another inferred scanner repair.

## Reproduction checkpoint

- `uv sync --locked --extra dev`: PASS.
- Requested exact vulture command: PASS, 1,326 findings / 1,326 reviewed identities, zero unclassified and zero never-allowlist. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. The old 21-versus-24 failure does not reproduce at this HEAD; no speculative test weakening.
- Read the frozen issue body's ten acceptance criteria. The existing profile explicitly labels the harness host-process preflight, not an exact production RC runner, and requires at least four hours for promotion. Existing tests distinguish local limiter enforcement from replica-selection non-bypass.

## Focused validation checkpoint

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,170 files.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`: 100 passed. This includes production limiter instances demonstrating fresh allowance by replica selection for both authenticated and unauthenticated identities; it is not a deployed multi-replica soak.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites, 29,499 unique identities, no duplicates. No tests changed or added; no inventory delta is needed.
- CI vulture arguments match `.github/workflows/vulture-ratchet.yml:82-85` and `quality.yml:1038-1041`.
- Current schema test independently enumerates the three previously missing audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173-177`; the production advisory-lock transaction still wraps all upgrades at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, accepted ADR-032, ADR-062 (including its retired entry-point warning), accepted ADR-081626-f383, and proposed ADR-081. ADR-081 is not an accepted waiver. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; durable execution authority and stale-writer fencing do not imply exactly-once external physical effects. Admission receipt deduplication cannot substitute for active-work recovery evidence. The process-local limiter is installed by production `main.py:648`; no new authorization path or cluster-wide policy is invented here.

## Final acceptance disposition

Additional executed checks:

- `uv run python -` imported the current `scripts/soak/run_soak.py`, loaded the unchanged `docs/testing/soak/evidence/m3a-round30-shakedown.json`, and asserted rejection for both `sustain_duration` and `exact_rc_artifact`: PASS. Recorded duration is 420.08 seconds; current runner returns `ok=false`, topology `host-uvicorn-preflight`. This evaluates historical evidence, not a fresh soak.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `git diff --check`: PASS.

Commands used 1,200-second validation timeouts. No current driver logs existed at intake; fresh command outputs were inspected directly and summarized here.

| Issue acceptance criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:153-172` names missing concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and reconciliation coverage. No selected-RC applicability decision is supplied. |
| Two production application replicas | **UNVERIFIED live at this HEAD.** `deploy/docker-compose.prod.yml:26-77` defines two replicas; executed ASGI tests do not establish two deployed RC images. |
| Sustained saturation, queue growth, lease reclaim, retry, leak and shutdown observations | **UNVERIFIED.** 420.08-second historical preflight rejected by the current evaluator; process-group sampler regressions passed but cannot establish long-window observations. |
| Physical-work uniqueness for schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED.** `run_soak.py:1045-1068` explicitly cancels the admission probe's queued Run without physical execution. No active Attempt/side-effect reconciliation performed in this round. |
| Rate/security/degraded behavior without replica-selection bypass | **Not satisfied by the tested limiter.** Fresh `test_replica_selection_has_an_independent_production_allowance` cases demonstrate `[200,200,429]` on each replica for the same identity (`tests/test_soak_promotion_gates.py:439-488`). Middleware is reachable through production `main.py:648`. Broader production concurrency/degraded behavior is **UNVERIFIED**. |
| Complete production telemetry with thresholds | **UNVERIFIED.** Driver-loop lag (`run_soak.py:1410-1417`) is not application-loop lag; sampler tests do not prove production pool saturation, query/lock latency, detached-worker census or sustained error bounds. |
| Active-work kill/restart with drain, fencing and recovery | **UNVERIFIED.** Boot cleanup tests passed; those do not prove active physical-work drain or reject stale Attempt effects after takeover. |
| Long exact-RC artifact/config soak | **UNVERIFIED / blocked.** Current runner always fails exact-RC identity (`run_soak.py:730-741`, wired at `1552`); selected historical evidence fails both identity and duration. No four-hour production run was started, and no candidate RC image/config is invented. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED completeness.** Existing human evidence records M3-A findings, but is historical and does not establish a complete current finding disposition. No GitHub mutation performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for candidate.** Existing historical packs are not evidence for this starting HEAD or a selected promotion artifact; all historical records preserved unchanged. |

## Handoff

Verdict: **BLOCKED**, not integration approval. Only this report changed. No source, test, gate, ledger, inventory or historical evidence edit was warranted by fresh CI reproduction. The old schema test failure is already repaired; the exact vulture ledger already matches its scan. Re-dispatching those same failures cannot close #860.

Next requires an explicit selected RC artifact/configuration and complete production-path workload/telemetry plan, resolution of the replica-selection budget mismatch through the existing canonical limiter/auth seam, and an executed >=4-hour exact-RC soak with physical-work recovery evidence. A longer invocation of the existing host preflight cannot satisfy the criterion. These are substantive remaining acceptance tasks, not scanner debt.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "resolve production soak prerequisites; issue acceptance remains blocked"}`. Focused CI validation is complete; issue completion is not claimed. Local report commit is required before handoff.
