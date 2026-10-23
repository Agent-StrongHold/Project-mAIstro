# Issue #860 validation — assigned round

## Scope and decision

This round processed only issue #860 at the assigned starting HEAD
`9f05eb26a2facb096e4559bc0f0640884317b211`. The supplied job directory had no
`check-*.log` files, so no driver verification logs were available to rely on.
The prior result (`62affb883de34b8da8193a93edd891fb/result.json`) was read as
historical context, not as fresh evidence. The worktree was clean initially;
there was no develop-sync conflict to resolve. No production RC artifact,
cluster deployment, or promotion configuration is available in this worktree.

Read the repository instructions and accepted ADR-081226-a66b (canonical
Run/NodeRun/Attempt lifecycle), ADR-081626-f383 (Attempt lease/fencing),
ADR-082426-82c7 (schedule-occurrence claims), and ADR-085 (per-principal
rate limiting). No issue language or test fixture overrides those ownership
contracts. In particular, the schedule admission claim is not physical Attempt
execution evidence, and no parallel scheduler or authorization authority is
introduced.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3373 files).
- `uv run python scripts/check-backlog-consistency.py` — passed (168 items).

The focused tests establish that the host-preflight promotion gate rejects
non-RC evidence and that independently instantiated production middleware has
independent allowance state (`tests/test_soak_promotion_gates.py:408-471,
480-527`). They do not establish cluster behavior or production soak acceptance.
No tests were added or modified; suite inventory delta is zero.

## Acceptance review against reachable behavior

| Criterion | Result and evidence |
|---|---|
| Representative release-candidate users/Workspaces, request mix, fan-out, schedules, queue, tools/models, Canvas and background traffic | **UNVERIFIED.** The profile explicitly records population, Graph/node fan-out, successful tools/models, Design/Canvas and Goal/background gaps (`m3a-load-profile.md:165-181`). Its current request mix is only an emulator profile (`:46-75`). |
| At least two production application replicas | **UNVERIFIED.** Existing evidence runs host uvicorn processes; profile states this does not exercise the exact Compose image/config (`m3a-load-profile.md:15-24`). |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leaks and shutdown/restart | **UNVERIFIED.** Round 109 observed 420.05 seconds vs 14400 minimum (`evidence/m3a-round109-shakedown.json:283-285`); the profile requires >=4 hours (`m3a-load-profile.md:139-150`). No new deployed soak was run. |
| Exactly-once schedules, task/Run/Attempt admission, Goal reconciliation and no duplicate physical work | **PARTIAL / UNVERIFIED.** Existing schedule evidence races admission only and cancels the resulting Run; the harness says nothing executes that Run (`run_soak.py:1064-1088`; `m3a-load-profile.md:208-218`). ADR-081626-f383 makes durable fencing of physical Attempts the relevant contract, but no cross-replica active Attempt kill/reclaim was observed. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | **NOT MET for non-bypass.** The production app installs `RateLimitMiddleware` (`packages/maistro-server/src/maistro_server/main.py:697`), whose constructor creates an `InMemoryRateLimiter` (`api/rate_limit.py:91-98`). Fresh regression test demonstrates separate production middleware instances each grant their own allowance (`tests/test_soak_promotion_gates.py:480-527`); the harness explicitly identifies process-local enforcement and aggregate budget as replica count × limit (`run_soak.py:1050`). BACKLOG.md classifies this as engine-116 and unresolved against issue acceptance (`:267-278`). Deployed security/degraded behavior remains unverified. |
| PostgreSQL usage/latency/locks, app event-loop latency, worker/process counts, RSS, descriptors, queue depth, errors/timeouts with thresholds | **PARTIAL / UNVERIFIED.** Preflight has some sampled metrics, but the profile says driver loop lag is not app-loop lag and worker/pool/lease/long-window observations remain unverified (`m3a-load-profile.md:165-181`). No production telemetry was collected. |
| Kill/restart during active work proves drain, fencing and recovery | **UNVERIFIED.** No live production Attempt was killed/restarted. The harness cancellation probe is admission cleanup, not active work (`run_soak.py:1064-1088`). |
| Long soak of exact promotable artifact/configuration | **NOT MET.** Host preflight always emits `exact_rc_artifact.ok=false`, and evidence duration is below the 4-hour threshold (`run_soak.py:19-21, 69, 1576, 1623-1626`; round-109 evidence `:224-227, 283-285`). Its captured head is `5a59c724...`, not the current assigned head (`m3a-round109-shakedown.json:70`). |
| Findings filed/reclassified to earliest broken invariant before promotion | **PARTIAL.** Existing backlog consistency gate passes and the documented process-local rate-budget gap is classified, but completeness for findings from a real RC soak is unverified because that soak has not run. |
| Machine-readable and human-readable evidence tied to exact image/package/commit/config hashes | **NOT MET for a promotable RC.** Round 109 is machine-readable but stale relative to this assigned head and identifies host preflight, not the exact RC image/config (`m3a-round109-shakedown.json:70,224-227`). The profile lists the production identity contract (`m3a-load-profile.md:25-44`). |

## Disposition

**BLOCKED / acceptance not complete.** These failures are evidence gaps or
reachable behavior gaps, not grounds to alter a promotion gate or manufacture
an acceptance claim. The host-preflight and regression tests are useful falsifiers
but cannot substitute for a designated immutable RC, representative deployed
traffic, the required >=4-hour run, full telemetry and active physical Attempt
recovery evidence. This round made no production-code/runtime change and added
no tests. No full-tree pytest, live database test, or production soak was run.
