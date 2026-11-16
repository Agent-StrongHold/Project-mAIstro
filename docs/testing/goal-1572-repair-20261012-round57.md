# #1572 repair lane — round 57 verification (2026-10-12)

Head `18676f9a86ca9e86d4bc09145dad041d8507a1e8`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. HEAD is **docs-only** over
`e7e4d341b6b71b0483dd50d2203fbca8cea531db` (`git diff --name-only
e7e4d341b..HEAD | grep -v '\.md$'` is empty; 20 doc files), so the rounds 37–56
code battery carries; the load-bearing legs below were nevertheless re-executed
first-hand at this head in fresh databases `r57g18` (pg18.6, lane container
auto-1572-pg :55712) and `r57g17` (pg17.11, auto-1572-pg17 :55717). The prior
driver job (155e69b9) died on a provider **timeout after all five checks had
already exited 0** — this round re-proves everything at the identical head.

## Driver checks (job 01bc1143d28b404ea2d6b962ec099f8b, all exit 0; 9-file set re-run first-hand)

- `uv sync --locked --extra dev` — resolved 256 / checked 214 packages.
- `uv run ruff check .` — "All checks passed!".
- `uv run ruff format --check .` — 3288 files already formatted.
- 9-file pytest set — **161 passed, 28 skipped** (skips are the PG legs; the
  453-run below runs those same legs with `MAISTRO_REQUIRE_PG_LEGS=1`, which
  turns a skip into a failure, at 0 skipped).
- `check-suite-inventory --suite packages/maistro-core/tests` — ok, 16334
  collected node IDs, 0 duplicates. No test files changed this round → no
  inventory delta.

## Sole blocker re-proven external (unchanged from rounds 37–56)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) → **exit 1**, sole finding: `maistro.goals.model::GoalStatus`
  NEW work-state vocabulary absent from trusted base 3c761d14db94 (19 → 20
  discovered), "no already-landed authorization".
- `quality/execution-lifecycles.json` at `origin/develop` has **0**
  `GoalStatus` occurrences; the branch banks it (1 row, :89, DOMAIN with
  rationale). `quality/ratchet-authorizations.json` has **0** `GoalStatus`
  entries on **both** sides. Ledger numstat vs develop is additive-only
  (17/0, 39/0, 4/0 — no row loss).
- Two-merge rule re-read in source this round:
  `scripts/ratchet_provenance.py:478 load_authorizations` resolves grants
  **from the base revision**; docstring: "a new grant does not take effect in
  the change that introduces it … two merges". An in-branch grant is a
  deliberate no-op; ordinary-PR grant/ledger edits are prohibited for this
  lane, and the CI-repair exception covers only `quality/vulture-baseline.json`.
- Vulture lane-repair path re-run at exact CI argv (quality.yml:1079):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323 reviewed
  identities → 1323 findings, unclassified 0. **Nothing to amend** — the
  lane-brief vulture repair step has an empty delta.
- CI test-job red reproduced first-hand:
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  → **1 failed / 28 passed**, same sole cause (the shipped-ledger gate asserts
  `gate.main() == 0` against the real base). The Coverage gate's producer is
  the same `pytest tests/` run, so it inherits this single red.
- `git fetch origin`; develop still `3c761d14db94` (merge-base == develop —
  nothing to merge, no sync conflict). The **only** unblock remains the
  grant-only landing of the GoalStatus authorization on develop — a maintainer
  action outside lane authority.

## Issue acceptance re-executed first-hand (all green)

- **Fresh install, both majors:** `r57g18` and `r57g17` migrated empty →
  head, final line `062 -> 063, The canonical Goal store`; stamp `063` on
  both; `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions` present on both; script directory reports a
  single head `063` with `down_revision = "062"`
  (`alembic/versions/063_canonical_goals.py:53-54`).
- **Conformance + binding + wiring + schema agreement + restart readback:**
  `packages/maistro-core/tests/goals` + `packages/maistro-core/tests/events`
  with `MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` and
  `MAISTRO_TEST_DATABASE_URL` at `r57g18` → **453 passed, 0 skipped**
  (conformance across memory/sqlite/postgres: append-only revisions with one
  CAS winner, stale-revision refusal, subgoal lineage preserving parent Goal
  and Project, foreign Goal indistinguishable from missing, immutable
  `goal_id`/`goal_revision` Run binding, Workspace-scoped authorization,
  restart readback). Goals-only re-run at `r57g17` → **70 passed, 0 skipped**.
- **Supported downgrade/reapplication:** `r57g18` `alembic downgrade 062`
  drops the Goal tables (count 3 → 0); `alembic upgrade head` reapplies
  (0 → 3).
- **Installed-base upgrades, both majors:**
  `tests/migrations/test_goal_installed_base_upgrade.py` → **8 passed** on
  fresh `r57ib18` (pg18) and **8 passed** on fresh `r57ib17` (pg17): merged
  identities keep their meaning; restored `056`/`057` files byte-identical to
  the merged snapshots; databases built by the actual develop snapshots
  `c560d4c` (user-model `056`), `4675101` (planner `057`) and HITL `061`
  forward-upgrade to `063` with **no stamp edit and no reset**; user-model
  facts/statement keys and a representative Run survive; planner indexes
  (`ix_canonical_runs_status_created`, …) and `ck_canonical_runs_status`
  intact; the three Goal tables exist; the durable Goal composition persists
  and reads back Goals, revisions and immutable bound Run provenance on the
  upgraded schema.
- **M1 convergence freeze:** `uv run python
  scripts/check-m1-convergence-freeze.py --base 3c761d14db94` (CI argv shape,
  formal-conformance.yml:77) → **exit 0**, no unapproved architecture island
  (no `GoalRun`, no second executor).
- **Production composition re-read:** `container.py:42/44` import,
  `:273` `goal_store` field, `:276-286` `goal_reader` → `ScopedGoalStore`,
  `:2414` `wire_goal_store(db_pool, pg_pool=pg_pool)` inside
  `create_container`, `:2701` passed to the constructor; Hive
  `packages/hive-conductor/backend/adapters/maistro_core.py:195` and
  maistro-server `packages/maistro-server/src/maistro_server/main.py:344`
  both build through `create_container`. `test_goal_wiring.py` (in the 453)
  proves the shipped Container exposes it.

## Disposition

Every issue acceptance criterion is proven by an executed test or command this
round. The three CI reds (test / Quality / Coverage) share the single external
cause above: the GoalStatus execution-lifecycle authorization must land on
develop first (two-merge rule, verified in gate + provenance source). Until
that grant-only landing happens, the branch cannot go green regardless of code
changes, and this lane may not self-grant. No code, test, or ledger changes
this round; no inventory delta.
