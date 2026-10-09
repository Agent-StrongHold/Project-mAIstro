# Issue #860 — bounded repair aaf5239f

## Frozen scope

- One issue: #860. Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `eea7cbe85837fd73a708898e072016842960d0d2`; supplied base `675db8be6c41b020ffffb224b2748c159c78a122` resolves in the local diff.
- Starting worktree clean; no incoming edits to salvage.
- Evidence snapshot: supplied dispatch-context.json, prior result bbb90441, prior check-3.log from 98a11313. Current job directory contains no check-*.log files at start.
- Repair candidates frozen: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production `pg_learnings.py`, `quality/vulture-baseline.json` only if the required scan finds reviewed retained identities, this report and a test inventory note if tests change. Inspect existing soak runner, promotion tests, profile, and evidence for acceptance only.
- No GitHub mutations, ref updates, gate weakening, or new execution authorities.

## Initial evidence / ambiguity

The supplied historical failure expects 21 schema statements but observes 24.
The previous result claims this is already repaired; that claim will be rerun.
The CI-repair instruction permits ledger amendments, but no scanner finding is
assumed until the exact command runs. The broader previous BLOCKED result concerns
missing exact-RC soak evidence, not a merge conflict. No develop merge is indicated.

## Results

- Exact vulture scan passed: 1326 findings, 1326 reviewed identities; zero
  unclassified/never_allowlist. Gate selected base e46ad6708fda. No ledger
  amendment is justified by actual findings.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped (1.39 s). Historical check-3 failure does not
  reproduce. The test already independently expects the three Gauntlet columns.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3195 files already formatted.
- Logs from this round: `/tmp/860-aaf-vulture.log`, `/tmp/860-aaf-schema.log`.

Both dispatched CI repair targets are verified passing without speculative
source/test/ledger edits. Database skips are not evidence of live PostgreSQL safety.

## Architecture and acceptance validation

Read repository AGENTS.md, docs/README.md and accepted ADRs 087 (schema evolution),
081626-f383 (Attempt lease fencing), 082426-82c7 (occurrence claims), 085
(principal rate limits), and 083026-a91e (absent measurements). No architectural
change: preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Occurrence
admission is not proof of unique physical execution; replica restart is not
proof of leased Attempt recovery. Process-local rate enforcement cannot waive
#860's replica-selection acceptance criterion.

Inspected the production schema transaction and adjacent independent SQL tests,
soak runner and regression tests, production RateLimitMiddleware, load profile,
human evidence and frozen round30 machine evidence. An initial read of the
nonexistent `maistro_server/middleware/rate_limit.py` returned ENOENT (not found;
skipped); the actual `api/rate_limit.py` path was taken from the test import and
read successfully. No code repair was inferred from this lookup error.

Additional executed checks:

- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q`: **74 passed**, 2.54 s; log `/tmp/860-aaf-targeted.log`.
- Imported the current runner using `uv run python` and asserted the evaluator
  returns exactly `['sustain_duration', 'exact_rc_artifact']` for
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`: **passed**.
  Observed 420.08 seconds versus 14400 required; topology is
  `host-uvicorn-preflight`. Also asserted the current artifact check is false.
  This reevaluates historical evidence; it is not a fresh load run.
- `uv run python scripts/check-shipped-surface-truth.py`: **passed**.
- `git diff --check`: **passed** before final report update.

### All ten issue criteria

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `docs/testing/soak/m3a-load-profile.md:152` lists absent users/Workspaces, Graph fan-out, successful model/tool calls, Canvas/Design and Goal workloads. No immutable RC-specific inclusion/exclusion contract supplied. |
| Two application replicas | **UNVERIFIED for RC.** Tests execute two limiter instances, not two deployed RC application replicas. Historical host-process topology fails the artifact gate. |
| Sustained saturation, growth, reclaim, retry, leak and restart observations | **UNVERIFIED.** Evaluated duration is 420.08 s; sampler regression tests measure real child growth but cannot establish long-window application stability or reclaim. |
| No duplicated physical work / Goal reconciliation | **UNVERIFIED.** HTTP admission-oracle regressions pass, but `m3a-load-profile.md:202` describes cancellation of the raced schedule Run without executing it. No production physical Attempt/Goal soak executed. |
| Rate/security/degraded behavior resists replica selection | **UNVERIFIED as a whole; contrary rate evidence reproduced.** `tests/test_soak_promotion_gates.py:439` exercises actual production middleware: identical principal/IP receives `[200, 200, 429]` on each replica independently. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents that scope. |
| Complete PostgreSQL/loop/process/RSS/fd/queue/error telemetry and thresholds | **UNVERIFIED.** Profile has thresholds, but explicitly distinguishes driver-loop from application-loop latency and lacks detached-worker/long-window measurements. Mocked probe tests are not production telemetry. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Boot cleanup regressions pass, not a new active physical-work drain or stale-worker fencing drill. |
| Long soak of exact RC configuration/artifact | **BLOCKED / UNVERIFIED.** Current runner at `scripts/soak/run_soak.py:730` explicitly rejects host-process artifact equivalence; executed evaluator rejects duration and artifact. Extending this preflight cannot fix artifact identity. |
| Findings filed/reclassified before promotion | **UNVERIFIED complete.** Human evidence records classifications and outstanding filing requirements. No GitHub mutation is permitted or performed here. |
| Machine/human evidence tied to exact image/package/commit/config | **UNVERIFIED for RC.** Historical formats exist and were inspected; neither the selected machine evidence nor runner establishes the promoted image/configuration. |

## Final handoff

**BLOCKED** on #860 acceptance, not on the dispatched schema/vulture checks.
Only this report changes. No new tests, inventory delta, source repair, ledger
amendment or authorization edit is justified by reproduced CI evidence. Existing
branch work and raw evidence are preserved. No service startup, full-tree pytest,
background commands, remote mutations or integration action occurred.

Required next input/work: select the immutable promotion RC image/configuration;
provide a production-topology runner with representative workload and full
telemetry; resolve the replica-selection requirement; then execute a minimum
four-hour soak with correlated physical Attempt fencing/recovery and publish its
exact-hash evidence. Do not redispatch the historical schema/vulture findings as
unresolved failures. A short preflight or a documentation commit cannot resolve
these acceptance prerequisites.

Progress: `{checked: 3, done: 2, skipped: 1, errors: 0, next: exact-RC acceptance}`.
The two completed items are the reported CI repair targets; the skipped item is
a new exact-RC soak. One harmless path lookup error was recovered as noted above.
This local handoff commit is not integration or promotion approval.
