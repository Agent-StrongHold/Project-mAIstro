# #1572 repair lane — round 55 verification (2026-10-12)

Head `d49a7aaf751470eb0c0ba59b1ba98acb4f1cbed3`, base `3c761d14db944a727fa0744444bc67cfe36d49f7`
(= `origin/develop` re-fetched this round). HEAD is **docs-only** over
`e7e4d341b6b71b0483dd50d2203fbca8cea531db` (`git diff --stat` with
`:(exclude)docs`/`*.md` is empty; 18 doc files), so the round 37–54 code battery
carries; every load-bearing leg below was nevertheless re-executed first-hand at
this head.

## Driver checks (job 5792d2439268479e8355140852fe2d85, all exit 0)

- `uv sync --locked --extra dev` — resolved 256 / checked 214 packages.
- `uv run ruff check .` — "All checks passed!".
- `uv run ruff format --check .` — 3288 files already formatted.
- 9-file pytest set — **161 passed, 28 skipped**.
- `check-suite-inventory` — ok, 16334 collected node IDs, 0 duplicates.

## Sole blocker re-proven external (unchanged from rounds 37–54)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) → **exit 1**, sole finding: `maistro.goals.model::GoalStatus`
  NEW work-state vocabulary absent from trusted base 3c761d14db94 (19 → 20),
  "no already-landed authorization".
- Branch banks `GoalStatus` (1 row in `quality/execution-lifecycles.json`);
  develop has 0. No `GoalStatus` grant in `quality/ratchet-authorizations.json`
  on **either** side (0 = 0).
- Two-merge rule read in source this round:
  `scripts/ratchet_provenance.py:478 load_authorizations` — grants are resolved
  from the **base revision**; the docstring states "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now two
  merges." An in-branch grant is therefore a deliberate no-op, and ordinary-PR
  grant edits are out of scope for this lane.
- `tests/test_check_execution_lifecycles.py` re-run:
  `test_the_shipped_ledger_matches_the_shipped_code` **1 failed / 28 passed** —
  the CI test-job red is the same sole cause (the test wraps the same scan).
- develop still `3c761d14db94` (fetch + ls-remote); merge-base == develop;
  nothing to merge, no sync conflict.
- `git diff --numstat origin/develop -- quality/` — additive-only
  (17/0, 39/0, 4/0), no row loss.
- Vulture CI-repair path empty: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0,
  1323 reviewed = 1323 findings**; nothing to amend in
  `quality/vulture-baseline.json`.
- No maintainer authorization in the dispatch snapshot (330 #1572 comments):
  the two newest are boilerplate started/blocked progress markers for jobs
  `bc48238…`/`af66306…`; none grants
  `execution-lifecycles -> maistro.goals.model::GoalStatus`.

## Acceptance re-executed first-hand this round (all at d49a7aaf)

- **Fresh install, pg18.6**: new database `r55g18` (lane container
  auto-1572-pg, 127.0.0.1:55712); `DATABASE_URL=... alembic upgrade head`
  migrated **empty → 063**, final step `062 -> 063, The canonical Goal store`;
  `alembic current`/`heads` = `063 (head)` single head; psql catalog shows
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`.
- **Goals + events suites, enforced PG legs** (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` at r55g18):
  `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/events -q`
  → **453 passed, 0 skipped** — shared conformance across in-memory/SQLite/
  PostgreSQL (Goal+GoalRevision round-trip), append-only revisions with
  stale-refusal and single-winner CAS, Subgoal lineage with recorded ownership
  transition, immutable Run `goal_id`/`goal_revision` binding, Workspace-scoped
  authorization (foreign == missing), PG catalogue schema agreement, durable
  restart readback.
- **Fresh install, pg17.11**: new `r55g17` (container auto-1572-pg17,
  127.0.0.1:55717) empty → `063 (head)`; goals suite enforced → **70 passed,
  0 skipped**. Both supported majors green this round.
- **Downgrade + reapplication** (r55g18): `alembic downgrade 062` drops all 3
  Goal tables; `upgrade head` re-runs `062 -> 063`, back at `063 (head)`,
  tables re-verified (3).
- **Installed-base leg 1 (`c560d4c` → user-model `056`)**: `git archive
  c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250` → /tmp/r55ib-c560 (head 056); fresh
  DB `r55ib56` migrated by the snapshot tree to **056**; seeded 2
  `user_model_facts` rows (+`persona_hints`) + 1 `user_model_statement_keys`
  row; forward upgrade with the candidate tree ended `062 -> 063`, no stamp
  edit, `063 (head)`. Post-upgrade: facts=2, keys=1 survive; goal_tables=3;
  planner_checks=2 (`ck_canonical_runs_status`,
  `ck_canonical_node_runs_status` present); readback + wiring on the upgraded
  DB → **11 passed**.
- **056/057 byte-identity**: `git diff origin/develop HEAD --stat --
  alembic/versions/056_user_model_facts.py alembic/versions/057_run_store_
  planner_stability.py` is empty (installed-base pre-states unchanged).
- **Production composition re-read**: `container.py:44` imports
  `wire_goal_store`; `create_container` wires it at `container.py:2414`; the
  `goal_reader` seam is derived as `ScopedGoalStore(goal_store,
  workspace_store)` at `container.py:276-286`. Both shipped compositions reach
  this through `create_container` (Hive
  `packages/hive-conductor/backend/adapters/maistro_core.py:195`; maistro-server
  `packages/maistro-server/src/maistro_server/main.py:344`).
- **Convergence freeze**: `uv run python scripts/check-m1-convergence-freeze.py
  --base 3c761d14db94…` (CI argv, formal-conformance.yml:77) → **exit 0**, no
  unapproved new architecture island (no `GoalRun`/second executor/second
  lifecycle).

## Resolution

The gate red clears only when the GoalStatus authorization lands on develop
first (two-merge) — a GitHub mutation outside this worker's authority. This is
the identical external blocker proven in rounds 37–54. No code, test, or ledger
changes this round; no inventory delta (no tests added or changed).
