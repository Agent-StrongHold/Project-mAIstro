# #1572 repair lane — round 58 verification (2026-10-12)

Head `db091060da05d1d82cfc298d29f3d9713d89e3d0`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. HEAD is **test-docs-only** over
`e7e4d341b6b71b0483dd50d2203fbca8cea531db`: 21 doc files plus one 3-line test
change (`db091060d`, `_PostgresBackend.store` in
`test_goal_store_conformance.py` now calls `ensure_goal_schema`), so the rounds
37–57 production-code battery carries. That one test change closed the focused
gap this round proves: the live PostgreSQL conformance leg had only ever been
exercised **skipped** at this head (driver 9-file set: 161 passed, 28 skipped),
so round 58 ran it live first-hand.

## Driver checks (job 51475b5c, all exit 0 at this exact head)

- `uv sync --locked --extra dev` — resolved 256 / checked 214 packages.
- `uv run ruff check .` — "All checks passed!" (re-run first-hand this round).
- `uv run ruff format --check .` — 3288 files already formatted (re-run
  first-hand).
- 9-file pytest set — **161 passed, 28 skipped**; skips are the PG legs, which
  the 453-run below executes with `MAISTRO_REQUIRE_PG_LEGS=1` (skip ⇒ failure).
- `check-suite-inventory --suite packages/maistro-core/tests` — ok, 16334
  collected node IDs, 0 duplicates. The `db091060d` delta is documented in
  `inventory-notes/1572-goal-pg-schema-ensure.md` (+2, verified against the
  recorded baseline — the inventory gate passes as shipped).

## Focused validation this round: the changed fixture, live (fresh databases)

- `r58g18` (pg18.6, lane container `auto-1572-pg` :55712) and `r58g17`
  (pg17.11, `auto-1572-pg17` :55717): both migrated **empty → head**, final
  line `062 -> 063, The canonical Goal store`; `alembic current`/`heads` = 063;
  `alembic/versions/063_canonical_goals.py:53-54` — `revision = "063"`,
  `down_revision = "062"`; all three `canonical_goal*` tables present on both.
- **Goals + events suites, live PG legs forced on**
  (`MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` and
  `MAISTRO_TEST_DATABASE_URL` at `r58g18`): **453 passed, 0 skipped** —
  conformance across memory/sqlite/**postgres** (the changed fixture), CAS
  append-only revisions with exactly one concurrent winner, stale-revision
  refusal, subgoal lineage preserving parent Goal and Project, foreign Goal
  indistinguishable from missing, immutable `goal_id`/`goal_revision` Run
  binding, Workspace-scoped authorization, schema agreement, restart readback.
- Goals-only at `r58g17`: **70 passed, 0 skipped** (second supported major).
- **Downgrade/reapplication** on `r58g18`: `alembic downgrade 062` drops the
  Goal tables (count 3 → 0); `alembic upgrade head` reapplies (0 → 3).
- **Installed-base upgrades, both majors, re-run at this head:**
  `tests/migrations/test_goal_installed_base_upgrade.py` → **8 passed**
  (pg18.6, throwaway `r58ib18`) and **8 passed** (pg17.11, `r58ib17`):
  databases built by the actual develop snapshots `c560d4c` (user-model
  `056`), `4675101` (planner `057`) and HITL `061` forward-upgrade to `063`
  with no stamp edit and no reset; merged identities keep their meaning;
  facts/keys and a representative Run survive; planner indexes and status
  constraints intact; the three Goal tables exist and read back through the
  durable composition.

## Sole CI blocker re-proven external (unchanged from rounds 37–57)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) → **exit 1**, sole finding: `maistro.goals.model::GoalStatus`
  NEW work-state vocabulary absent from trusted base 3c761d14db94 (19 → 20
  discovered), "no already-landed authorization".
- `origin/develop` unchanged at `3c761d14db94` (`git fetch`; merge-base ==
  develop — nothing to merge). `quality/ratchet-authorizations.json` carries no
  GoalStatus grant there; ledger numstat vs develop additive-only (17/0, 39/0,
  4/0 — no row loss). Two-merge rule re-read in source this round:
  `scripts/ratchet_provenance.py:478 load_authorizations` resolves grants
  **from the base revision** — an in-branch grant is a deliberate no-op, and
  this lane may not self-grant.
- CI test-job red reproduced first-hand:
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  → **1 failed / 28 passed**, same sole cause; the Coverage gate's producer is
  the same `pytest tests/` run and inherits this single red.
- **Vulture CI-repair path empty** at exact CI argv (quality.yml:1079):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323 reviewed
  identities → 1323 findings, unclassified 0. Nothing genuinely dead to fix and
  nothing to amend in `quality/vulture-baseline.json`.
- Dispatch snapshot (342 comments, captured 2026-10-12T04:19Z): newest entries
  are automated progress markers; no maintainer authorization for the
  GoalStatus grant.

## Remaining acceptance legs re-read at this head

- **M1 convergence freeze:** `uv run python
  scripts/check-m1-convergence-freeze.py --base 3c761d14db94` → **exit 0**, no
  unapproved architecture island (no `GoalRun`, no second executor).
- **Production composition:** `container.py:44` import, `:273` `goal_store`
  field, `:276-286` `goal_reader` → `ScopedGoalStore`, `:2414`
  `wire_goal_store(db_pool, pg_pool=pg_pool)` inside `create_container`; Hive
  `packages/hive-conductor/backend/adapters/maistro_core.py:195` and
  maistro-server `packages/maistro-server/src/maistro_server/main.py:29` both
  compose through `create_container`; `test_goal_wiring.py` (in the 453)
  proves the shipped Container exposes the store.

## Disposition

Every issue acceptance criterion is exercised by an executed test or command at
this head; the changed live-PG fixture is now proven against both supported
majors instead of a skip. The three CI reds (test / Quality / Coverage) share
one external cause: the GoalStatus execution-lifecycle authorization must land
on develop first (two-merge rule, verified in gate + provenance source). Until
that grant-only maintainer landing, the branch cannot go green regardless of
in-branch changes. No code, test, or ledger changes this round; no inventory
delta.
