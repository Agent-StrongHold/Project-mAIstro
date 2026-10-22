# #1572 round-54 repair-lane verification at a82a847aa877 (2026-10-12)

Verifier/writer round. Base 3c761d14db944a727fa0744444bc67cfe36d49f7
(`git fetch` + `git ls-remote origin develop` this round — **still unchanged**;
merge-base == develop, so there is no develop sync to merge), head
a82a847aa8770da2ea75c7b03bbfe3e6c9a9e054, tree clean at start. No code, test,
ledger or workflow edits made; no inventory delta (no test additions, so no new
`docs/testing/inventory-notes/` entry is required). This note is the round's
only artifact, committed per the writer rule. HEAD is docs-only over
b4674898dce072498a9e1ea55f16085b222f0d53 (`git diff --name-only b4674898..HEAD`
= this file's predecessor only) and has **0 non-docs diffs** vs
e7e4d341b6b71b0483dd50d2203fbca8cea531db (re-counted this round), so the
rounds 37–53 battery carries; the load-bearing legs were nevertheless
re-executed first-hand at this head, as listed below.

## Driver checks (job af663067a47843d7b4acef4fcf15a4d1, check-0..4.log) — all green

- `uv sync --locked --extra dev` ok (Resolved 256 / Checked 214).
- `uv run ruff check .` — "All checks passed!"; `uv run ruff format --check .`
  — 3288 files already formatted.
- Driver 9-file pytest set: **161 passed, 28 skipped** (skips are the PG legs,
  executed enforced below).
- `check-suite-inventory.py --suite packages/maistro-core/tests` — ok, 16334
  unique identities, 0 duplicates, 0 redundant bytes.

## Sole CI blocker — re-proven external, first-hand this round

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) — **exit 1**, sole finding: `maistro.goals.model::
  GoalStatus: NEW work-state vocabulary is absent from the trusted base and
  has no already-landed authorization` (19 classified -> 20 discovered; base
  printed as 3c761d14db94).
- CI `test` red reproduced: `uv run pytest
  tests/test_check_execution_lifecycles.py -q` -> **1 failed / 28 passed**
  (`test_the_shipped_ledger_matches_the_shipped_code`, tests/
  test_check_execution_lifecycles.py:374, identical GoalStatus stdout). The
  root `tests/` suite is also the Coverage gate's `--source=scripts` producer,
  so all three CI reds (test, quality architecture job, coverage gate) trace
  to this one cause.
- Two-merge mechanics re-read in source this round:
  `scripts/ratchet_provenance.py:478 load_authorizations` resolves grants via
  `resolve_baseline(path, base=base, ...)` — **from the merge base** — and its
  docstring states the consequence verbatim ("a new grant does not take effect
  in the change that introduces it ... two merges"). An in-branch grant is a
  no-op by design and grant edits are prohibited in ordinary PRs.
- Ledger facts re-checked: candidate `quality/execution-lifecycles.json:89`
  banks GoalStatus (DOMAIN, rationale naming #1572, explicitly not a second
  execution identity); `git diff --numstat origin/develop -- quality/` is
  additive-only (ac-state-notes +17, durable-table-retention +39,
  execution-lifecycles +4; no row loss); `grep -c GoalStatus
  quality/ratchet-authorizations.json` = 0 on the branch.
- The lane brief's vulture CI-repair path checked and **empty**:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact quality.yml:1078-1082
  argv) — **exit 0, 1323 reviewed = 1323 findings**; nothing to amend in
  `quality/vulture-baseline.json`.
- No maintainer authorization in the dispatch snapshot: all 327/328 comment
  matches in dispatch-context.json are boilerplate progress markers ("does not
  close the issue or authorize merge/deployment"); none grants
  `execution-lifecycles -> maistro.goals.model::GoalStatus`.
- Resolution: the gate red clears only when the GoalStatus authorization lands
  on develop first (two-merge) — a GitHub mutation outside this worker's
  authority. This is the identical external blocker proven in rounds 37–53.

## Acceptance re-executed first-hand this round (all at a82a847)

- **Fresh install, pg18.6**: new database `r54g18` (lane container
  auto-1572-pg, 127.0.0.1:55712); `DATABASE_URL=... alembic upgrade head`
  migrated **empty -> 063**, final step `062 -> 063, The canonical Goal
  store`; `alembic current`/`heads` = `063 (head)` single head; psql catalog
  shows `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`.
- **Goals + events suites, enforced PG legs** (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` plain at r54g18):
  `uv run pytest packages/maistro-core/tests/goals
  packages/maistro-core/tests/events -q` -> **453 passed, 0 skipped** —
  shared conformance across in-memory/SQLite/PostgreSQL (Goal+GoalRevision
  round-trip), append-only revisions with stale-refusal and single-winner CAS,
  Subgoal lineage with recorded ownership transition, immutable Run
  `goal_id`/`goal_revision` binding, Workspace-scoped authorization (foreign
  == missing), PG catalogue schema agreement, durable restart readback.
- **Fresh install, pg17.11**: new `r54g17` (container auto-1572-pg17,
  127.0.0.1:55717) empty -> `063 (head)`; goals suite enforced -> **70
  passed, 0 skipped**. Both supported majors green this round.
- **Downgrade + reapplication** (r54g18): `alembic downgrade 062` then
  `upgrade head` re-runs `062 -> 063`, version back at `063 (head)`, 3 Goal
  tables re-verified.
- **Installed-base leg 1 (`c560d4c` -> user-model `056`)**: `git archive
  c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250` to /tmp/r54ib-c560; fresh DB
  `r54ib56` migrated by the snapshot tree to its head **056**; seeded 2
  `user_model_facts` rows + 1 `user_model_statement_keys` row; forward
  upgrade with the candidate tree ended `062 -> 063`, no reset, no stamp
  edit, `063 (head)`. Post-upgrade: facts=2, keys=1 survive; goal_tables=3;
  planner_checks=2 (`ck_canonical_runs_status`,
  `ck_canonical_node_runs_status` present); readback + wiring on the
  upgraded DB -> **11 passed**.
- **Installed-base leg 2 (`4675101` -> planner `057`)**: `git archive
  4675101647e629d290e0fece29694e43883e1395` to /tmp/r54ib-4675; fresh DB
  `r54ib57` migrated by the snapshot tree to its head **057**; seeded 1 fact
  + 1 key; forward upgrade `062 -> 063`, no stamp edit. Post-upgrade:
  facts=1, keys=1; goal_tables=3; planner_checks=2; readback + wiring ->
  **11 passed**.
- **Migration identity re-proven**: `git diff origin/develop HEAD --stat --
  alembic/versions/056_user_model_facts.py
  alembic/versions/057_run_store_planner_stability.py` is empty (merged
  identities byte-identical); `alembic/versions/063_canonical_goals.py` has
  `down_revision = "062"` — appended after the integrated develop head;
  single head re-confirmed by `alembic heads` (= `063 (head)`).
- **Convergence freeze at CI argv** (`uv run python
  scripts/check-m1-convergence-freeze.py --base 3c761d14db94...` per
  formal-conformance.yml:77) — **exit 0**, "no unapproved new architecture
  island" (no GoalRun/OrchestratorRun/second executor).
- **Production composition re-read in source**: `container.py:44` imports
  `wire_goal_store`/`ScopedGoalStore`; `create_container` calls
  `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` at
  `container.py:2414`; the principal-carrying `goal_reader` ->
  `ScopedGoalStore(self.goal_store, self.workspace_store)` property at
  `container.py:276-286`; both shipped compositions build the Container via
  `create_container` (Hive `packages/hive-conductor/backend/adapters/
  maistro_core.py:195`, maistro-server `packages/maistro-server/src/
  maistro_server/main.py:344`); `test_goal_wiring.py` (inside the 453-passed
  run) proves the shipped Container exposes it.

## Verdict for this round

Implementation acceptance is fully proven locally; the sole red is the
external, maintainer-gated execution-lifecycles authorization (two-merge
rule). Nothing further is actionable inside this worktree: vulture amendment
path empty, develop unchanged (no grant to merge), no authorization in the
dispatch snapshot.
