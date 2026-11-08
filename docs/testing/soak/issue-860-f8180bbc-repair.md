# Issue #860 repair — f8180bbc

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `57f6a8ec0d715ac00bbb436e82641d0535db0630`; supplied base: `435dc1937e0407ab4de198ffcced49860bb14ad2` (both resolved).
- Starting tree clean. No salvage or develop-sync conflict present.
- Inspect only the supplied dispatch snapshot, schema-fence implementation/test, soak harness/profile/promotion tests, adjacent production middleware, applicable ADRs and quality gates.
- Potential repair files frozen: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` (only if the exact scan demonstrates reviewed retained debt), this report, and `docs/testing/inventory-notes/860-f8180bbc-schema-fence.md` if test changes are needed.
- Supplied prior failure: `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log` reports 24 schema statements versus 21 expected. Reproduction pending; no guessed repair.
- Current job directory contains no `check-*.log`; prior result reports missing designated RC artifact/configuration and independent replica rate allowances. These claims require fresh inspection/validation.
- Assumption: this is a writer CI-repair round, not authority to select the release candidate or introduce new scheduling/authorization paths. No GitHub mutations.

## Progress

- Exact vulture scan passed: 1323 findings / 1323 reviewed identities, zero unclassified and never-allowlist findings. No ledger amendment is warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. The supplied failure is stale: lines 171–175 already expect the three Gauntlet audit columns, matching production lines 116–118. No test or production repair is justified by that log.
- Existing profile explicitly states the host-process harness cannot sign RC promotion and lists representative workload/telemetry gaps. No long-running RC soak has been run.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **66 passed**. Includes two real production middleware instances demonstrating independent rate allowances, the four-hour preflight CLI rejection, process-group measurements, and task backpressure handling.
- Latest comments in the frozen dispatch snapshot describe the preceding blocked attempt, not selection of an immutable RC. No external issue/PR list was refreshed.
- `uv run python scripts/check-deployment-claims.py`: **passed** (component existence, not runtime deployment proof).
- `uv run python scripts/check-merge-markers.py`: **passed**.
- `uv run python scripts/check-backlog-consistency.py`: **passed**, 168 items.
- `git diff --check`: **passed**.

## Architecture reconciliation and reachable behavior

Read `AGENTS.md`, `docs/README.md`, accepted ADR-081226-69ee (Graph/Node),
ADR-081626-f383 (Attempt leases/fencing), ADR-085 (principal rate limits), and
**Proposed** ADR-081 (deployment). Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`. The fencing ADR explicitly excludes lease-expiry takeover from its
current boundary; this round cannot invent reclaim authority to satisfy an issue
checkbox. ADR-085 requires principal-keyed limits but does not establish a shared
replica budget. These boundaries do not waive #860 acceptance.

Production installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; its constructor builds
an `InMemoryRateLimiter` at `api/rate_limit.py:94`. Freshly executed tests at
`tests/test_soak_promotion_gates.py:439` use that middleware with the same client
and credential across two ASGI instances. Each returns `[200, 200, 429]` while
the exhausted first instance continues rejecting. This proves independent
allowances, not a deployed concurrent security soak or cluster-wide enforcement.

`deploy/docker-compose.prod.yml:10–12` identifies itself as a reference artifact
requiring production image pinning. The application services build locally and
require an external model gateway. No immutable promotion RC/configuration was
designated in this assignment. `scripts/soak/run_soak.py:730–741` correctly returns
`exact_rc_artifact.ok=false` for its host-process topology. The executed CLI tests
at `tests/test_soak_promotion_gates.py:103` reject even synthetic four-hour evidence
when the artifact record is missing, null or preflight. Running this emulator
longer cannot discharge the artifact prerequisite.

## Acceptance matrix

| # | Criterion | Fresh evidence / remaining gap |
|---|---|---|
| 1 | Representative RC load profile | **UNVERIFIED**. Profile `m3a-load-profile.md:151–168` admits missing concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas, Goal/background traffic. Applicability needs the selected RC. |
| 2 | At least two application replicas | **UNVERIFIED at RC grade**. Two ASGI middleware instances tested, not a deployed two-replica RC. No deployment launched this round. |
| 3 | Sustained saturation, growth, expiry/reclaim, retry/backoff, leaks and restart | **UNVERIFIED**. Sampler/accounting tests pass, but no long-running load observations were collected. |
| 4 | No duplicate physical work across replicas | **UNVERIFIED**. Profile lines 199–204 explicitly distinguish the one-occurrence admission race (queued probe Run cancelled without execution) from physical Attempt/Goal proof. |
| 5 | Concurrent rate/security/degraded behavior; no replica-selection bypass | **NOT PROVEN**. Executed production middleware tests demonstrate additional allowance after replica selection. Task backpressure tests pass; full deployed security behavior remains unverified. |
| 6 | Complete telemetry and explicit pass/fail thresholds | **UNVERIFIED at RC grade**. Profile lines 163–168 distinguish driver lag from application-loop lag and identify missing worker/saturation/reclaim observations. |
| 7 | Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED**. Cleanup regression tests pass; process rejoin or terminal rows do not establish physical-work recovery. |
| 8 | Long soak of exact RC artifact/configuration | **BLOCKED / UNVERIFIED**. No designated immutable RC/configuration; current harness always rejects artifact equivalence. No new soak performed. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED externally**. Existing rate-scope finding revalidated locally. No GitHub mutation, per assignment. No new load findings claimed. |
| 10 | Machine/human soak evidence tied to exact hashes | **UNVERIFIED for RC**. This report binds deterministic checks to the starting HEAD, not to a deployed RC. Historical preflight bundles are not fresh release evidence. |

## Handoff

Only this report changed. No new/changed tests, so no inventory delta is needed.
No source, ledger, grant or gate edits are justified by the reproduced checks.
No merge conflict was present and no destructive operation was performed.
This is a **BLOCKED** handoff, not integration approval or certification of the
accumulated branch diff.

To resume: designate the immutable RC and normalized production configuration;
resolve the replica-budget acceptance discrepancy through the canonical security
path; complete the production-path workload/telemetry coverage and execute the
required long soak. Any code/runtime configuration change requires a new soak.
Do not redispatch the stale 24-versus-21 schema failure as a new repair without
fresh failing evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC selection and production soak prerequisites"}`.
Focused deterministic validation completed; issue acceptance remains blocked.
