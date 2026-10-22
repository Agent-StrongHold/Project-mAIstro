# #1572 repair lane — round 56 verification (2026-10-12)

Head `ce44b4fbc4706119fb82b00a476c251d9c690791`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. HEAD is **docs-only** over
`e7e4d341b6b71b0483dd50d2203fbca8cea531db` (`git diff --name-only e7e4d341b..HEAD
| grep -v '\.md$'` is empty; 19 doc files), so the rounds 37–55 code battery
carries; the load-bearing legs below were nevertheless re-executed first-hand at
this head in fresh databases `r56g18` (pg18.6, lane container auto-1572-pg) and
`r56g17` (pg17.11, auto-1572-pg17).

## Driver checks (job 7a68c1bed03d466cb3a62ab7d07b5866, all exit 0)

- `uv sync --locked --extra dev` — resolved 256 / checked 214 packages.
- `uv run ruff check .` — "All checks passed!" (re-run first-hand this round too).
- `uv run ruff format --check .` — 3288 files already formatted (re-run).
- 9-file pytest set — **161 passed, 28 skipped**.
- `check-suite-inventory --suite packages/maistro-core/tests` — ok, 16334
  collected node IDs, 0 duplicates. No test files changed this round → no
  inventory delta.

## Sole blocker re-proven external (unchanged from rounds 37–55)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) → **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus` NEW work-state vocabulary absent from
  trusted base 3c761d14db94 (19 → 20 discovered), "no already-landed
  authorization".
- `quality/execution-lifecycles.json` at `origin/develop` has 19 rows and **0**
  occurrences of `GoalStatus`; the branch banks it (1 row). No `GoalStatus`
  grant in `quality/ratchet-authorizations.json` at `origin/develop` (0).
- Two-merge rule re-read in source this round:
  `scripts/ratchet_provenance.py:478 load_authorizations` — grants are resolved
  **from the base revision**; docstring: "a new grant does not take effect in
  the change that introduces it. Authorizing a floor-raise is now two merges."
  An in-branch grant is a deliberate no-op; ordinary-PR grant/ledger edits are
  prohibited for this lane.
- Gate mechanics re-read in source: `check-execution-lifecycles.py:705
  _unauthorized_additions` keeps an addition unauthorized unless it is granted
  at the base **or** already visible at the base source (`_discover_at_revision`,
  :674 — `maistro/goals/model.py` is new in this branch, so not visible).
  There is no third path.
- `tests/test_check_execution_lifecycles.py` re-run:
  `test_the_shipped_ledger_matches_the_shipped_code` **1 failed / 28 passed** —
  the CI test-job red is the same sole cause (the test wraps the same scan).
- Lane-named CI-repair path (vulture per-identity ledger) still empty:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323 reviewed =
  1323 findings — nothing to amend in `quality/vulture-baseline.json`, and the
  failing gate is the execution-lifecycles ratchet, not vulture.
- develop still `3c761d14db94` (fetch; `git rev-parse origin/develop` =
  merge-base = base). No sync conflict, nothing to merge, no grant to inherit.
- Dispatch snapshot re-scanned (859 comment-like entries across 95 sources,
  captured 2026-10-12T02:21Z): **zero** mentions of GoalStatus authorization;
  newest entries are unrelated bot boilerplate. No maintainer authorization.

## Acceptance re-executed first-hand this round (all at ce44b4fbc)

- **Fresh install, pg18.6**: new database `r56g18` (127.0.0.1:55712);
  `DATABASE_URL=… uv run alembic upgrade head` migrated **empty → 063**, final
  step `062 -> 063, The canonical Goal store`; `alembic current` = `063 (head)`
  single head; psql catalog: `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`.
- **Goals + events suites, enforced PG legs** (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` = plain
  `postgresql://…/r56g18`):
  `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/events -q`
  → **453 passed, 0 skipped** — shared conformance across in-memory/SQLite/
  PostgreSQL (Goal+GoalRevision round-trip), append-only revisions with
  stale-refusal and single-winner CAS, Subgoal lineage with recorded ownership
  transition, immutable Run `goal_id`/`goal_revision` binding, Workspace-scoped
  authorization (foreign == missing), PG catalogue schema agreement, durable
  restart readback.
- **Fresh install, pg17.11**: new `r56g17` (127.0.0.1:55717) empty →
  `062 -> 063`, `063 (head)`; goals suite enforced → **70 passed, 0 skipped**.
  Both supported majors green this round.
- **Downgrade + reapplication** (r56g18): `alembic downgrade 062` drops all 3
  Goal tables (psql count 0); `upgrade head` re-runs `062 -> 063`, back at
  `063 (head)`, tables re-verified (3).
- **Convergence freeze** at exact CI argv (formal-conformance.yml:77):
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94`
  → exit 0, "no unapproved new architecture island" — no GoalRun/second
  executor/second lifecycle.
- **Production composition re-read**: `packages/maistro-core/src/maistro/container.py:44`
  imports `wire_goal_store`, `:276-286` derives the authorized `goal_reader`
  (`ScopedGoalStore` over the canonical Workspace store), `:2414`
  `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` inside
  `create_container`; both shipped compositions go through `create_container`
  (Hive `packages/hive-conductor/backend/adapters/maistro_core.py:195`,
  maistro-server `packages/maistro-server/src/maistro_server/main.py:344`).

## Verdict

Unchanged from rounds 37–55: **BLOCKED** on an external, policy-mandated
two-merge step. Every acceptance criterion of #1572 is proven green at this
head; the only red is the execution-lifecycles ratchet requiring
`maistro.goals.model::GoalStatus` to be authorized by a grant **already landed
on the base** (or the row landed on the base ledger) before this branch may
carry it. That is a maintainer action on `develop`; no in-lane edit can fix it
without self-authorization, which the gate (and lane policy) explicitly close.
No code, test, or ledger changes were made this round; no inventory delta.
