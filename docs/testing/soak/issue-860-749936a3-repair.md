# Issue #860 — repair job 749936a3

## Frozen scope

- Assigned issue: #860 only; writer/CI-repair role.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `d9b3fe45d87bbd355a56bc89ab7a7b5dfa7bc688`.
- Supplied develop base: `15157c6f2bc57d5f7dc7d9e212adb323864d32ef` (resolved by local diff).
- Process the exact vulture gate, then focused soak acceptance validation; no remote mutations, merge, or unrelated repairs.
- Candidate edits frozen to this report, `quality/vulture-baseline.json` if the mandated scan identifies reviewed retained debt, and existing issue #860 soak harness/tests/profile/evidence summary only if a concrete failure requires repair. Any added test requires an inventory note.
- Read-only validation scope: repository instructions, relevant execution/scheduler/fencing/rate ADRs, CI gate definitions, existing soak artifacts, adjacent admission and persistence tests.

## Initial observations

- No uncommitted work to salvage.
- Supplied prior result was read; it reports Docker unavailable and no promotable RC soak. These are historical claims, not current validation.
- Job directory snapshot contains `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`; no driver `check-*.log` files exist to inspect. Assumption: execute checks locally rather than claim absent logs passed.
- This is not a develop-sync conflict (clean index); do not fetch or merge unrelated changes.

## Results

- Mandated `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, exit 0; 1,359 findings match 1,359 reviewed identities at base `15157c6f2bc5`. Zero unclassified / never-allowlist findings. No ledger amendment is justified; no scanner defect was reproduced.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info`: FAIL, exit 1; cannot connect to daemon. Docker CLI exists but is not evidence of a usable runtime. Do not retry the same environmental blocker or fabricate a live run.
- Current profile explicitly labels the host-uvicorn runner non-promotable and lists missing Workspace/fan-out/Goal/Design/model coverage. No immutable RC image/configuration is designated by this job; do not guess one.

- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 2,774 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped** in 2.71 seconds. All skips explicitly require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL claim. Existing regressions execute production middleware (independent `[200, 200, 429]` allowances on both replicas), actual task-route/spine admission backpressure and real child-process resource sampling. Mocked probes and ASGI instances are not a deployment soak.
- Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-085, and ADR-082126-f69c (supersedes ADR-046). Reconciliation: physical identity is Attempt, not Run; stale-writer fencing is not by itself lease-expiry reclaim; recurrence produces canonical Runs, never a second scheduler. ADR-085 requires principal-keyed limiting but does not mandate a shared store. Preserve those boundaries rather than invent a runtime or authorization path to make #860 pass.
- The old H3 shared-limiter claim is already corrected in `m3a-soak-evidence.md:171`; current middleware explicitly documents process-local state. No cosmetic re-repair warranted.

- Relevant CI commands checked against workflow definitions: `uv run python scripts/check-deployment-claims.py`, `uv run python scripts/check-execution-lifecycles.py`, `uv run python scripts/check-merge-markers.py`: all PASS (19 classified/discovered execution lifecycles).
- Imported `scripts/soak/run_soak.py` with `uv run python` and evaluated the four frozen historical JSON packs through `failed_promotion_checks`. All four fail `sustain_duration` and `exact_rc_artifact`: `m3a-soak-evidence.json` and `m3a-repair-validation.json` each fail seven gates; `m3a-round5-final.json` fails three (90.17 seconds); `m3a-round6-shakedown.json` fails two (90.43 seconds). Assertions requiring duration and artifact rejection passed. This checks recorded flags, not independent validity of other historical observations.
- Production wiring verified: `maistro_server/main.py:588` installs `RateLimitMiddleware`; `api/rate_limit.py:72` creates its process-local limiter. `api/tasks.py:117` catches `RunConcurrencyExceeded` as retryable admission backpressure. `run_soak.py:947-975` cancels the schedule probe Run without executing physical work. Reference Compose declares two applications but uses a local build and mutable dependency tags, not a designated immutable RC.

## Acceptance disposition

| # | Criterion | Executed evidence / remaining gap |
|---|---|---|
| 1 | Representative release-candidate profile | PARTIAL: inspected profile defines mix and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool, Design/Canvas and Goal traffic. Applicability to a selected RC is UNVERIFIED. |
| 2 | Two application replicas | Reference Compose declares two applications. Exact-RC deployment execution UNVERIFIED; Docker daemon unreachable. ASGI instances are not live deployment evidence. |
| 3 | Sustained saturation, queue, lease reclaim, retries, memory/descriptor/process leaks | UNVERIFIED: all historical packs rejected on duration/artifact. Sampler regressions are not a long-window load run. |
| 4 | Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: schedule probe admits then cancels its Run; no physical Attempt correlation or sustained Goal reconciliation proof. |
| 5 | Rate/security/degraded non-bypass under concurrency | NOT MET for aggregate principal allowance: executed real middleware tests reproduce independent allowances on replicas. Complete RC security/degraded-load behavior UNVERIFIED. No new authorization path introduced. |
| 6 | Complete telemetry and explicit thresholds | PARTIAL: profile reviewed and process-group sampler tests passed; application-loop latency, complete worker census, pool saturation/lock observations and qualifying RC metrics UNVERIFIED. |
| 7 | Kill/restart during active work; drain/fencing/recovery | UNVERIFIED: no live deployment/restart run this round. Historical exit/rejoin and terminal Run counts cannot establish physical-work uniqueness or no silent loss. |
| 8 | At least four-hour exact-RC soak | BLOCKED: no selected immutable RC/configuration in assignment, daemon unavailable, current runner explicitly rejects exact-RC equivalence. No qualifying soak executed. |
| 9 | Findings filed/reclassified to earliest broken invariant | PARTIAL: existing F11/F12 records classify harness evidence validity at M3-A rather than alleging runtime duplication. External filing UNVERIFIED; GitHub mutation prohibited. No new load findings this round. |
| 10 | Machine/human evidence tied to exact artifact/configuration hashes | PARTIAL: existing packs preserved and evaluated; none qualifies as promotion evidence. Exact-RC hash-bound soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not an integration approval. The previous block is not a develop-sync conflict. The requested debt gate is green; changing its ledger would manufacture a repair. Only this report changes; no source, runtime configuration, tests, historical packs, ledgers or grants were edited. No tests added, so no inventory delta is required.

Next owner must provide a usable container runtime and designate the immutable RC/configuration, settle the rate-limit acceptance mismatch, supply a representative production-topology runner with physical Attempt correlation and complete application metrics, then run at least four hours on the unchanged artifact. Any code/runtime-config change requires a fresh soak. Do not repeat short emulator runs as a substitute.

Progress: checked 1 issue; done 0 (acceptance blocked); skipped 0 issues; errors 1 (Docker environment); next: external RC/runtime prerequisites and production-soak implementation. Five PostgreSQL test cases explicitly skipped. Local checkpoint commit required; no remote action.
