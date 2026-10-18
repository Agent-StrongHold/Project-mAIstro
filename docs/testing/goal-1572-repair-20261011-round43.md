# #1572 round-43 verification record (2026-10-11, head 42d289286ec47, base 3c761d14db94)

Repair-lane round at the round-42 doc commit's head (unchanged). Driver job
`2e7810e8…` completed all five deterministic checks green; this round
re-executed every acceptance leg and the red reduction first-hand on fresh
databases, including the installed-base migration legs by name. No code,
test, or ledger changes; no inventory delta.

## Driver checks (job 2e7810e8…) — logs read, results accepted

| check | result |
|---|---|
| `uv sync --locked --extra dev` | ok |
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 3288 files already formatted |
| driver 9-file pytest set `-q -x` | 161 passed, 28 skipped (PG legs off) |
| `check-suite-inventory.py --suite packages/maistro-core/tests` | ok, 16334 identities, 0 duplicates |

## Issue acceptance — executed first-hand this round

- **Code frozen**: `git diff --name-only e7e4d341b..HEAD` excluding `docs/`
  is empty (0 files) — `alembic/`, `packages/`, `quality/`, `scripts/`,
  `tests/`, `.github/` byte-identical since the round-37 full battery, so
  that evidence carries by construction; everything below was still
  re-executed fresh.
- **Goals suite, PG legs enforced on BOTH majors, fresh databases**: created
  `r43g18` (pgvector:pg18 :55712) and `r43g17` (pgvector:pg17 :55717),
  `alembic upgrade head` empty→**063** each (final step `062 -> 063, The
  canonical Goal store`), `\dt canonical_goal*` → exactly `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` (pg18 catalog);
  then `pytest packages/maistro-core/tests/goals` with
  `MAISTRO_REQUIRE_PG_LEGS=1` and **both** DSN vars → **72 passed, 0
  skipped on pg18** (incl. `test_goal_wiring.py`,
  `test_goal_restart_readback.py`, `test_run_goal_binding.py`,
  `test_goal_store_conformance.py` memory/sqlite/postgres legs and the
  schema-agreement class) and **70 passed on pg17**. Operator note re-hit
  and confirmed: with only `MAISTRO_TEST_PG_DSN` set,
  `test_goal_pg_schema_agreement` fails closed 6× on the empty
  `MAISTRO_TEST_DATABASE_URL` (by design; plain `postgresql://` scheme).
- **Installed-base upgrade legs by name (pg18)**:
  `tests/migrations/test_goal_installed_base_upgrade.py` +
  `tests/migrations/test_migration_chain.py` → **26 passed**: merged
  identities keep their meaning with Goals appended after them; restored
  files byte-identical to the merged snapshots; a database at merged `056`
  has user-model tables and no Goal tables; forward upgrades from real
  develop snapshots `c560d4c`(→056), `4675101`(→057) and HITL
  `66f3cea9`(→061) with no reset and no stamp edit; the upgraded bases
  serve the durable Goal composition (both snapshots). **pg17 mirror: 8
  passed.**
- **Production composition**: `create_container` wires `goal_store`
  (`packages/maistro-core/src/maistro/container.py:2414` via
  `wire_goal_store`; authorized `ScopedGoalStore` seam at `:286`); Hive
  adapter (`packages/hive-conductor/backend/adapters/maistro_core.py:195`)
  and maistro-server
  (`packages/maistro-server/src/maistro_server/main.py:344`) both build
  through `create_container`.
- **Convergence freeze** (CI argv, formal-conformance.yml:77):
  `check-m1-convergence-freeze.py --base 3c761d14db94` → exit 0.
- **Vulture** (CI argv, quality.yml:1077): `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  1323 reviewed identities -> 1323 findings — **no amendment applies** even
  though this is a CI-repair round.
- **Closure keywords**: 0 matches for `(fixes|closes|resolves) #1572`
  across `git log 3c761d14..HEAD --format=%B`.

## Sole remaining blocker — external, re-proven first-hand this round

- `scripts/check-execution-lifecycles.py` (CI argv, quality.yml:1541) →
  **exit 1**, single finding: `maistro.goals.model::GoalStatus: NEW
  work-state vocabulary is absent from the trusted base and has no
  already-landed authorization`.
- CI's red `test` job reproduced locally:
  `tests/test_check_execution_lifecycles.py` → 1 failed
  (`test_the_shipped_ledger_matches_the_shipped_code` asserting
  `gate.main()==0`), 28 passed.
- Structural facts re-read from source this round:
  - `scripts/ratchet_provenance.py:478` `load_authorizations` reads grants
    **from the base revision** (two-merge rule; a branch self-grant is
    unread by design).
  - `git show 3c761d14db94:quality/execution-lifecycles.json` → 0 GoalStatus
    rows; the branch carries exactly one DOMAIN row
    (`quality/execution-lifecycles.json:89`).
  - `git ls-remote origin develop` → still exactly
    `3c761d14db944a727fa0744444bc67cfe36d49f7`: **the grant-only develop
    landing has not happened**; no sync conflict (develop unmoved).
- Mechanical sufficiency re-proven with no tree edit: the unmodified gate
  `main()` with only a GoalStatus grant injected in-memory at
  `load_authorizations` (pre-registered as the gate's `_ratchet_provenance`
  module) → **exit 0**, 20/20 vocabularies classified (3 CANONICAL, 8
  CONVERGE, 7 DOMAIN, 2 PROJECTION). No in-branch edit can legitimately
  flip the gate: removing the vocabulary guts the issue's acceptance;
  editing the test or scanner weakens a gate; both prohibited.

Unblock (outside this lane's authority): land the GoalStatus
execution-lifecycles authorization on develop as a grant-only commit to
`quality/ratchet-authorizations.json`, then resync auto-1572 and re-queue.
