# verify-37-585cd8d

Independent verification record for lane L37 (#37 — M1-A1 canonical
Workspace/Membership ownership and persistence) at head
`585cd8d26015c90d41d927e2905fa1c62730b0ff` (develop base
`f36810882a5fc3afc23547e615b6f9156c10b502`). Supersedes the round at
`e64557d7cc` + repair `4c433682b5`: the head moved by merging develop, so
every claim below was re-executed at the merged head. No test counts move —
this note records executed evidence only.

## What the head adds over the verified repair

The merge brings develop's clean-install proof round (gate-c.yml,
mutation.yml, `tests/release/`, `scripts/prove-installed-workspace.py`,
frontend lockfiles). `git diff 4c433682b5..585cd8d260 --name-only` touches
none of the four repair files
(`test_workspace_orphan_disposition_migration.py`,
`test_pg_recovery_disposition_events.py`,
`test_pg_two_worker_cancellation_1242.py`, `test_recovery_event_seam.py`)
and none of the #37 production fence
(`projects/scope_store.py`, `projects/pg_scope_store.py`,
`workspaces/pg_store.py`, `alembic/versions/071_*.py`).

## Executed at this head

Environment: pgvector/pg18 at `127.0.0.1:5433`, fresh database
`maistro_fresh` (created for this round, CI-shaped: unmigrated for the
migration suites), `MAISTRO_REQUIRE_PG_LEGS=1`.

- CI step 1 — `pytest tests/migrations` against the unmigrated database:
  **173 passed** (254s).
- CI step 2 — `alembic upgrade head` on the same database: chain applies
  cleanly to revision **071**.
- The round's original repro pair, one shared pytest session —
  `persistence/test_workspace_orphan_disposition_migration.py` +
  `workspaces/test_wiring.py`: **12 passed** (pre-repair shape: 1 failed,
  `'canonical_workspaces' in ''`). The repair's subprocess shape is intact
  at head (`_alembic` runs `python -m alembic` with `DATABASE_URL` scoped
  to the child; same pattern as `tests/migrations/test_migration_chain.py`).
- CI coverage-postgres ordering from `.github/workflows/quality.yml`
  (persistence, test_container_postgres, events,
  capabilities/test_backend_effect_context, runs, graph, projects,
  workspaces, personas, goals, scheduling, tasks/test_idempotency_purge_driven,
  tasks/test_pg_admission_atomicity_live, security/test_elevation_durable,
  security/test_delegation_durable, memory/user_model, quota) in ONE
  pytest session: **7653 passed, 99 skipped, 4 xfailed, 0 failed** (522s).
  This is the session the repaired file used to break downstream
  log-assertions in; it is green end to end at this head.
- CI's separate backlog invocation: **115 passed, 2 skipped**.
- Hive-conductor authority/journal durability with PG legs on —
  `test_workspace_authority.py` + `test_workspace_authority_durable.py`:
  **41 passed, 0 skipped** (the 11 PG legs that skip without a DSN all run).
- #1419 presentation-map pins (AC-6): the two named tests in
  `test_workspace_authority.py` — **2 passed**.
- `uv run ruff check .` — pass; `uv run ruff format --check .` — 3684 files
  formatted.
- `uv run python scripts/check-suite-inventory.py` — **21/21 suites match**
  the recorded inventory (37223 node IDs, 0 duplicates).
- Fence production code intact at head: `scope_store.py` raises
  `WorkspaceNotFound` on cache hit and miss; `pg_scope_store.py` fences with
  `SELECT 1 ... FOR UPDATE` before the root insert. AC-1's new-pool restart
  leg lives at `test_workspace_scope_fence_pg.py:228`.
- Closure keywords: 0 matches for `fixes|closes|resolves #` across all
  branch commit messages since the develop base; PR #2525 body says only
  "Refs #37".

## Acceptance map (AC -> executed evidence)

- AC-1 (same canonical ID/membership/Root on Hive and server, new-process
  PG restart) -> restart leg in the green ordering session + the 41-passed
  hive durable run.
- AC-2 (unknown/deleted ids fail BEFORE writes, zero rows) -> fence tests
  in `projects/`, `workspaces/`, `persistence/`, all inside the 7653-passed
  session.
- AC-3 (PG two-replica races cannot mint/preserve unauthorized Root/Run) ->
  `runs/` + persistence fence-race tests in the same session.
- AC-4 (missing/interrupted/corrupt journals; auditable quarantine) ->
  41-passed hive authority/journal run above.
- AC-5 (orphan disposition preserves provenance, no new admissions) ->
  orphan-disposition migration file + `test_workspace_tombstones.py` in the
  green session, plus the fresh-DB chain apply to 071.
- AC-6 (#1419 representation map) ->
  `docs/architecture/WORKSPACE-DATA-OWNERSHIP-MAP.md` present; its two
  presentation pins executed above.
