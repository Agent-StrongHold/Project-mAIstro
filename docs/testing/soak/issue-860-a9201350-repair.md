# Issue #860 — repair checkpoint a9201350

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`4c7adab86ac08072b66806becda1a52ebeb7e182`, base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Initial worktree clean; no salvage required. No current-job `check-*.log`
files were present in the supplied job directory.

Process the supplied schema-fence failure, exact vulture gate, and existing
soak acceptance probes, in that order. Candidate implementation files are
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`, its adjacent
`tests/persistence/test_pg_learnings.py`, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, and (only if scanner evidence requires)
`quality/vulture-baseline.json`; this checkpoint and an inventory note may
record results. Other production architecture is inspection-only.

Prior result reports missing exact-RC production soak evidence. Assumption:
this is not a develop-sync conflict; do not fetch or merge unrelated changes.
No acceptance claim is inherited from prior reports.

## Completed CI checks

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The supplied old failure is already repaired:
  the independent ordered DDL assertion includes the three Gauntlet audit
  columns at lines 173–175. No further schema-test edit is justified.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **passed**, 1322 findings / 1322 reviewed identities, zero unclassified or
  never-allowlist findings. No ledger amendment is warranted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **73 passed**. Includes real production middleware and task-router ASGI
  probes, not merely synthetic evidence dictionaries.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3301 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: **passed**, all 17 suites,
  31323 unique collected identities. No tests added or modified; no inventory
  delta or ledger changes.

## Architecture and acceptance reconciliation

Read repository instructions, the documentation authority hierarchy, and
accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle) and ADR-081626-f383
(lease fencing). Admission identity is not proof of physical-work uniqueness;
lease expiry alone does not authorize a competing reclaim scheduler. No new
execution, persistence, security, or reconciliation authority is introduced.

Fresh probes reproduce rather than resolve the outstanding production-seam
limitations: `tests/test_soak_promotion_gates.py:439` exhausts one principal's
allowance on one production middleware instance, then observes a fresh
allowance on the other (authenticated and unauthenticated). At line 564 the
production task router returns an admitted receipt locally but 404 on the
peer queue sharing the same canonical admitter. These use in-process ASGI
replicas; they are not deployed-production soak evidence.

`run_soak.py:744` correctly refuses exact-RC equivalence. The executed
four-hour-evidence CLI tests prove missing, null, and host-preflight artifact
records exit 1. Running this emulator for longer cannot resolve that blocker.
No exact RC artifact or selected production configuration was supplied for a
new promotion-signing run; none is guessed.

| Issue acceptance | Result in this repair |
|---|---|
| Representative users/Workspaces, mix, Graph fan-out, schedules, tools/models, Canvas and workers | UNVERIFIED. `m3a-load-profile.md` explicitly omits representative surfaces; inspected, not waived. |
| At least two production application replicas | UNVERIFIED. Two-instance production-code ASGI probes passed, not two deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks, shutdown/restart | UNVERIFIED. No long deployed-RC run executed. |
| No duplicate physical schedule/task/Run/Attempt work and Goal reconciliation | UNVERIFIED. Existing admission/gate tests do not establish physical-work uniqueness. |
| Security/rate/degraded enforcement cannot be bypassed by replica selection | NOT PROVEN. Executed production middleware probe reproduces independent per-replica allowances. Backpressure tests pass but do not establish a cluster budget. |
| PostgreSQL, application-loop, worker, RSS/FD, queue and error telemetry with thresholds | UNVERIFIED at production grade. Sampler regressions pass; driver loop measurements are not application event-loop telemetry. |
| Kill/restart during active work; drain/fencing/recovery without loss/duplication | UNVERIFIED. No active-work production restart executed. |
| Long soak of exact RC artifact/config, rerun after changes | UNVERIFIED. CLI regression demonstrates fail-closed artifact gate, not a successful RC soak. |
| Classify all load findings to earliest broken invariant | UNVERIFIED for completeness. Existing findings inspected; no GitHub mutations performed. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for production RC. This record binds local checks to the starting head only. |

## Handoff

Verdict: **BLOCKED**, not integration approval. Both supplied CI repair
leads are already clean on this exact head; changing production code or the
vulture ledger without a reproduced defect would be speculative. Only this
validation checkpoint changed. Existing implementation and evidence retained.

Progress: checked 1 assigned issue; done 0; skipped 0; errors 0 in the current
validation commands. Next: provide the immutable RC image/configuration and a
production-path workload covering the omitted acceptance surfaces; resolve
replica budget/receipt semantics through their existing canonical owners, then
execute and publish the long active-work soak. Do not rerun a short host
preflight or alter gates to claim issue completion.
