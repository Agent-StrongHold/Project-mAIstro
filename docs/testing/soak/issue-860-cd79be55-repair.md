# Issue #860 repair — cd79be55

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Verified starting HEAD: `174b3e1e550794c80529ad92872ce77f094ec516`.
- Assigned base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial worktree clean; no incoming work to salvage.
- Process the supplied dispatch snapshot, prior result, and reported check-3.log;
  do not refresh GitHub or enumerate further repair items.
- Candidate edits: this handoff; `quality/vulture-baseline.json` only if the
  mandated scan identifies reviewed retained debt; soak implementation/tests
  only if fresh evidence identifies a focused repair (with inventory note).
- No check-*.log files were present in this job directory at initial listing.
- Prior result is evidence, not verification. Production soak acceptance must
  not be inferred from ASGI unit probes or a successful quality scan.

## Progress

- Supplied historical check-3.log reports 24 DDL statements versus 21 expected.
  Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passes: 37 passed, 6 skipped (live database coverage not established).
- Mandated `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passes: 1,322 reviewed identities / 1,322 findings; zero unclassified or
  never-allowlist findings. No ledger repair is supported by this evidence.
- Fresh logs: `writer-vulture.log` and `writer-pg-learnings.log` in the assigned
  job directory. Historical failure is not reproducible at the assigned HEAD.
- Assumption: this is the explicit writer/repair lane, not the read-only verifier
  lane. No merge conflict exists; the conditional develop-sync instruction does
  not apply.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,301 files).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 73 tests. Logs: `writer-ruff.log`, `writer-format.log`,
  `writer-soak-tests.log`. These are not deployed soak results.
- Read repository instructions, documentation authority map, accepted
  ADR-081226-a66b (lifecycle), ADR-081626-f383 (execution fencing), and
  ADR-073126-c4e1 (release provenance). Canonical execution remains
  Goal → Graph → Run → NodeRun → Attempt. The fencing ADR explicitly does
  not define lease-expiry takeover; admission uniqueness cannot substitute
  for physical-work recovery evidence. No competing scheduler/reclaim
  authority or release-artifact equivalence will be invented for this issue.

## Fresh production-boundary findings

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:214` fences
  schema upgrades in one transaction; the independent test oracle at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:174` already
  includes the three audit columns missing from the historical failing log.
  No test weakening or schema repair is needed.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` explicitly
  documents per-process budgets, and line 94 creates a limiter per middleware
  instance. The executed parametrized test at
  `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on each
  instance for the same authenticated/unauthenticated identity. Local
  enforcement is not the issue's stronger replica-selection-resistant budget.
- `packages/maistro-server/src/maistro_server/api/tasks.py:137` reads the
  local queue. The executed production-router probe at
  `tests/test_soak_promotion_gates.py:564` observes owner 200 and peer 404
  after canonical admission. It does not conceal the 404 with affinity.
- `deploy/docker-compose.prod.yml:26` defines built application containers
  with shared services, whereas `scripts/soak/run_soak.py:744` declares the
  host-process runner non-equivalent. Its threshold construction calls this
  check; the executed CLI tests reject missing/null/preflight identity even
  with synthetic four-hour duration. These tests do not deploy the RC.
- One attempted read of `maistro_server/middleware/rate_limit.py` returned
  not found; skipped. The test's explicit import resolved the actual
  `maistro_server/api/rate_limit.py`, which was read. No unresolved ref was
  used for a git operation.

## Acceptance disposition

| # | Issue criterion | Executed evidence and remaining gap |
|---|---|---|
| 1 | Representative RC users/Workspaces, request mix, fan-out, schedules, tools/models, Canvas and workers | **UNVERIFIED**. Profile reviewed; its remaining-gaps section explicitly excludes several required surfaces. Harness accounting tests do not establish representativeness. |
| 2 | Two supported application replicas | **UNVERIFIED** for the exact RC. Fresh tests instantiate separate ASGI apps, not deployed containers. |
| 3 | Sustained saturation, queues, reclaim, retries, memory/fd/process leaks and shutdown | **UNVERIFIED**. Linux process-group sampler tests pass; no sustained production load executed. |
| 4 | No duplicate physical work across replicas | **UNVERIFIED**. Admission oracle tests pass but do not execute physical Attempts across restart/reclaim. Accepted fencing ADR does not authorize invented expiry takeover. |
| 5 | Rate/security/degraded behavior effective without replica-selection bypass | **UNMET** for a shared allowance: the real middleware probe reproduces independent budgets. Full deployed security/degraded behavior remains **UNVERIFIED**. |
| 6 | PostgreSQL usage/latency/locks, application loop, workers/RSS/fds/queue/errors with thresholds | **UNVERIFIED** at RC scope. Sampler/accounting coverage passes; driver loop metrics are not application loop telemetry. |
| 7 | Kill/restart active replica proves drain/fencing/recovery | **UNVERIFIED**. No production replica killed this round; exit/rejoin and terminal Run counts cannot prove physical-work recovery. |
| 8 | Long soak of exact RC artifact/config; repeat after changes | **UNVERIFIED / BLOCKED**. Runner's exact-artifact gate deliberately fails; rejection tests pass. No immutable promotion artifact was selected or soaked in this round. |
| 9 | Findings filed/reclassified to earliest broken milestone | **UNVERIFIED** for completeness/external filing. Local findings preserved here; no GitHub mutations authorized or performed. |
| 10 | Machine/human evidence bound to exact hashes | **UNVERIFIED** for RC soak. Fresh job logs and this head-bound report are validation evidence only, not image/config-bound soak evidence. |

## Handoff

**BLOCKED.** The old deterministic failure and proposed ledger repair require
no changes at this HEAD; fresh evidence does not justify cosmetic repair.
Only this report changed. No tests added/removed/renamed, so no inventory delta
is required. No gates, grants, ledger, runtime config, or historical evidence
changed. Existing work was preserved.

Next prerequisite: select the immutable RC and supported configuration, resolve
the replica-budget contract and missing production workloads/recovery probes,
then run the profile's >=4-hour exact-RC soak with hash-bound telemetry. Another
identical preflight or CI-only retry cannot establish these missing criteria.
No long preflight was launched merely to manufacture elapsed-time evidence.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
validation failures 0 (one missing-path read noted above). Investigation complete;
acceptance remains blocked. Commit this report locally, with no integration or
promotion approval and no remote action.
