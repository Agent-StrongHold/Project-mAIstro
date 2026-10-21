# Issue #65 — current repair checkpoint

Frozen scope: issue #65, branch auto-65, starting HEAD 0c41278595561ef3e0240b7bb36e801cff274612; supplied base 5f714e1beed5efbc589234acb78bdf96f811b651. No GitHub mutations or other issue work.

Files in scope: existing Goal/Run inspection services/routes, adjacent core Goal context, frontend inspection pages and their tests/inventory notes; quality/vulture-baseline.json only for the explicitly authorized exact-debt-ledger repair; this report. Inspect governance and validation scripts without changing gates.

Initial observations: worktree clean, HEAD matches assignment. Supplied job directory has no check-*.log files. Prior findings are hypotheses to revalidate against this HEAD. Direct base-to-head diff includes unrelated history; do not discard or repair that history. Writer role assumed from explicit repair assignment.

Progress: `uv sync --locked --extra dev` passed. Exact vulture scan passed: 1,321 findings / 1,321 reviewed identities, no unbanked debt. No ledger amendment justified. Existing source confirms projection-only Goal discovery remains. Next focused repair: discover canonical Goals and bound Runs through existing scoped owner APIs, retaining legacy compatibility and shared Run identity. Broader decision/effect inspection remains separately unproven. Owner inspection shows GoalStore has no enumeration and ScopedRunReader has no discovery API; do not scan private dictionaries from Conductor. Focused repair therefore extends the existing Goal/Run protocols, in-memory/SQLite/Postgres implementations, and scoped readers with bounded discovery, then consumes those seams. Exact additional files: maistro/goals/{store,sqlite_store,pg_store,authorization}.py; maistro/runs/{store,sqlite_store,pg_store,scoped_reads}.py and adjacent conformance/scoped-read tests. No new owner/store/authority. Attempted goals/access.py does not exist; skipped; actual owner is goals/authorization.py.

Checkpoint: new owner discovery tests first failed for missing method. New HTTP regressions both failed with empty lists before service changes. After scoped owner + shared inspection changes, all 33 Goal tests passed, including zero-Run Goal and projection-free multi-Run/backlink/dedup cases. Scoped/owner discovery tests: 8 passed, 3 PostgreSQL skips (not evidence). Adjacent canonical Run test still asserted the former projection-only limitation; updated it to assert canonical discovery/status and no projection write. Shared Run controls are unchanged. ADR reconciliation: extend canonical owner query capabilities per ADR-081226-9944/a66b and ADR-082826-d9f5; no private index or lifecycle.

Read scope expands only to actual test fixtures, existing store schema/query helpers and validation scripts needed for these changes. Remaining issue acceptance still includes Invocation/effect/Event/decision trace, browser restart/navigation and complete historical pagination; do not claim issue completion from this focused discovery repair.

Validation checkpoint: full Conductor suite reached 3,422 passed / 14 skipped, then exposed an existing #65 page accessibility regression: DagRuns.tsx's named legacy activity SVG lacks role=img. This is in the assigned Run inspection page and is evidenced by test_svg_accessible_names.py:98; repair the markup without weakening the test. Root lint initially found one nested async-with style issue; fixed. Project scope normalization remains in the Goal consumer so the shared Run overlay does not broaden its compatibility contract. Exact changed-surface SVG repair is added to scope. PostgreSQL discovery validation now passed: started isolated `auto-65-discovery-pg` from pgvector/pgvector:pg18 on loopback port 18665, migrated through 063 with `uv run alembic upgrade head`, then ran all 11 new owner/scoping cases with MAISTRO_REQUIRE_PG_LEGS=1 (11 passed, no skips). No existing databases touched. Container will be stopped (not deleted) after validation.

Core Goal/Run directories: 1,318 passed, 315 environment-gated skips, 6 aiosqlite thread warnings. Vulture still clean, 1,321/1,321, no ledger changes warranted. Both inventory gates pass (core 16,520, Conductor 3,776); route permissions, frontend typed-client, frontend API routes and API route contracts pass. Final backend rerun passed: 3,757 passed, 19 skipped, 36 warnings in 173.97s. Frontend `npm run build` passed (TypeScript and Vite). Final root Ruff check and format check passed (3,333 files), and `git diff --check` passed.

## Acceptance audit (issue-body order)

These results are a partial repair, not integration approval. All named Python
cases ran in the suites above; no browser execution or full process restart was
performed this round.

1. Shared #1036 seam: new canonical-only HTTP history case and existing identity,
   detail/control tests pass; discovery is added to the shared seam, not a second
   list/control owner. Browser interaction remains UNVERIFIED.
2. Canonical Goal/Agent/Run/Event reads: Goal and Run discovery now reach production
   HTTP handlers without a projection; zero-Run Goals are visible. Agent is still
   an identity field; canonical Event history remains UNVERIFIED/absent from this
   inspection projection.
3. Exact revision/accountability/intent/Subgoals/Graphs/Runs: existing Goal tests
   and zero-Run test pass. Current reconciliation decision/blocker authority is
   still absent; execution disposition is not a reconciliation decision.
4. Unified histories: sequential, retry/child and new two-canonical-Run HTTP
   history tests pass, including no duplicate when a retained projection arrives.
   Full concurrent producer-to-browser lifecycle remains UNVERIFIED.
5. Run terminal state is not Goal terminal state: completed/failed Run tests and
   canonical Goal state/revision test pass; new history retains active Goal.
6. Run identity/status/control parity: canonical inspection tests pass, including
   projectionless cancellation and list/detail status. No control code changed.
7. Restart/reconnect: reopened Goal-store enumeration passes on durable backends;
   full live/historical browser restart/reconnect is UNVERIFIED.
8. Retry/replan/child/delegation/HITL provenance: existing retry, child/delegation
   and HITL provenance tests pass; complete producer-to-browser flow UNVERIFIED.
9. State distinctions: existing waiting-human/blocked/terminal tests pass;
   zero-Run Goals now say no execution evidence, not work settled. Canonical
   suspended/stopping/reconciliation reasons remain UNVERIFIED.
10. Failure/security/approval to execution and reconciliation: NOT MET. The Run
    detail still exposes NodeRuns/Attempts and optional creative artifacts, not
    Invocation/effect/approval decision joins or reconciliation-decision evidence.
11. Goal -> Graph/Run -> Attempt/effect/artifact -> back: HTTP Goal/Run/backlink and
    physical NodeRun/Attempt tests pass. Effect navigation absent; browser path
    and non-creative artifact trace remain UNVERIFIED.
12. Canonical product language: PARTIAL. Zero-Run empty state/disposition is now
    accurate, but the existing Run page still says Live DAG Runs. Not repaired
    cosmetically in lieu of the missing execution/decision behavior.
13. No competing store/runtime: only query methods on the existing canonical
    Goal/Run stores and scoped readers were added. Existing projection-no-write
    test passes; no scheduler, authorization policy, or lifecycle mutation added.

## Residual risks / next steps

- Bounded discovery is not complete historical pagination: newest 100 Goals per
  Workspace and recent hot Runs only; the existing Goal service also caps its
  shared Run evidence window across visible Workspaces. Old Goal deep links and
  complete histories outside that window still need owner-backed pagination/
  by-Goal lookup, not private indexes. Cold Run payloads remain by-id only.
- Query filters use existing Workspace columns and Run payload creation times;
  no new index/migration was introduced. Large-scale query cost is UNVERIFIED.
- Core directory suite skipped 315 environment-gated cases; new PG cases were
  separately executed, not counted as proven from skips. Runtime warnings remain
  (aiosqlite thread cleanup, Pydantic serialization, test-client cookies).
- Invocation/effect/Event/approval/reconciliation decisions and full persistent
  browser navigation remain substantive #65 work. Do not close the issue.

## Commands / evidence

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed twice, 1,321 identities; no ledger amendment.
- `uv run pytest packages/maistro-core/tests/goals/test_goal_store_conformance.py packages/maistro-core/tests/runs/test_spine_conformance.py -k 'goal_discovery or recent_run_discovery' -x -q`: first RED missing owner method; then 4 passed / 2 PG skips before real-server run.
- `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -k 'without_runs or canonical_only_goal_history' -q`: RED, both empty-list regressions before service change.
- Focused Goal/canonical-Run/creative suite exposed the old expected non-discovery assertion and an over-broad Project overlay change. Updated the former contract assertion; kept canonical Project normalization local to Goal inspection, rather than changing shared compatibility overlay.
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs -x -q`: 1,318 passed / 315 skipped; `/tmp/auto-65-core.log`.
- Isolated pgvector/pg18, `DATABASE_URL=... uv run alembic upgrade head`: passed through 063; `/tmp/auto-65-migrate.log`.
- `MAISTRO_TEST_PG_DSN=... MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/goals/test_goal_store_conformance.py packages/maistro-core/tests/runs/test_spine_conformance.py packages/maistro-core/tests/runs/test_scoped_reads.py -k 'discovery or recent_discovery' -x -q`: 11 passed, no skips.
- `uv run pytest packages/hive-conductor/backend/tests -x -q`: first failed named-SVG role (3,422 passed); final 3,757 passed / 19 skipped; `/tmp/auto-65-backend-final.log`.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`: final passes.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` and `--suite packages/hive-conductor/backend/tests`: passed.
- `uv run python scripts/check-route-permissions.py`, `check-frontend-typed-client.py`, `check-frontend-api-routes.py`, `check-api-route-contracts.py`: passed.
- `cd packages/hive-conductor/frontend && npm run build`: passed; `/tmp/auto-65-frontend-build.log`.

Changed files: eight canonical store/reader modules, two inspection services,
two Conductor inspection tests, three core test modules, two inspection pages,
this handoff and the inventory note. No ledger, grants, gates, or generated files
changed. Inventory delta: core +11, Conductor backend +2.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#65 historical pagination and decision/effect/Event inspection"}`.
Verdict: NEEDS-REPAIR. Focused discovery repair complete; whole issue not complete.

