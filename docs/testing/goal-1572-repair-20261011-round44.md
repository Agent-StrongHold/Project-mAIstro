# #1572 round-44 verification record (2026-10-11, head 8112c5be85e9205d6abc54eedc85e2c48cca7364, base 3c761d14db94)

Repair-lane round at the round-43 doc commit's head (unchanged). The round-43
worker run died on a provider timeout after its driver checks had all returned
0 (`jobs/3bdd0f93…/result.json`: `failure_kind: provider_error`), so this
round re-executed the driver battery and every acceptance leg first-hand on
fresh databases, including both installed-base migration fixtures by name.
No code, test, or ledger changes; no inventory delta.

## Driver checks — re-executed first-hand this round

| check | result |
|---|---|
| `uv sync --locked --extra dev` | ok (resolved 256, checked 214) |
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 3288 files already formatted |
| driver 9-file pytest set `-q` | 161 passed, 28 skipped (PG legs off) |
| `check-suite-inventory.py --suite packages/maistro-core/tests` | ok, 16334 identities, 0 duplicates |

## Issue acceptance — executed first-hand this round

- **Code frozen**: `git diff --name-only e7e4d341b..HEAD` is exactly the seven
  `docs/testing/goal-1572-repair-*-roundNN.md` notes — `alembic/`,
  `packages/`, `quality/`, `scripts/`, `tests/`, `.github/` byte-identical
  since the round-37 full battery; everything below was still re-executed
  fresh against the current tree.
- **Goals suite, PG legs enforced on BOTH majors, fresh databases**: created
  `r44g18` (pgvector:pg18 :55712) and `r44g17` (pgvector:pg17 :55717);
  `alembic upgrade head` empty→**063** each (final step `062 -> 063, The
  canonical Goal store`), single head, `\dt canonical*` shows exactly the
  three Goal tables (`canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`) on both majors. With
  `MAISTRO_REQUIRE_PG_LEGS=1` + `MAISTRO_TEST_PG_DSN` +
  `MAISTRO_TEST_DATABASE_URL`: `pytest packages/maistro-core/tests/goals/ -q`
  → **70 passed** on pg18 and **70 passed** on pg17 (skips become failures
  under the require flag, so this is the full conformance matrix: round-trip,
  append-only/CAS, subgoal lineage, ownership transition, cross-principal
  isolation, binding immutability, schema agreement).
- **Installed-base leg 1 (`c560d4c` → user-model `056`)**: `git archive
  c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250` to `/tmp/r44ib-c560`; fresh DB
  `r44ib18` migrated by the snapshot tree to its head **056**; representative
  `user_model_facts` + `user_model_statement_keys` rows inserted; forward
  upgrade with the candidate tree ran `056 -> 057 -> … -> 062 -> 063` with no
  reset and no stamp edit, ending **063 (head)**. Post-upgrade catalog: facts
  and statement-key rows survive unchanged (1/1), the 3 Goal tables exist,
  and both planner status CHECKs added by merged `057`
  (`ck_canonical_runs_status`, `ck_canonical_node_runs_status`) are present.
  Durable-composition readback on the upgraded DB:
  `test_goal_restart_readback.py` + `test_goal_wiring.py` → **11 passed**.
- **Installed-base leg 2 (`4675101` → planner `057`)**: `git archive
  4675101647e629d290e0fece29694e43883e1395` to `/tmp/r44ib-4675`; fresh DB
  `r44ib57` migrated by the snapshot tree to its head **057** (both planner
  CHECKs pre-existing); representative fact row inserted; forward upgrade
  with the candidate tree `057 -> … -> 062 -> 063`, no stamp edit, ending
  **063 (head)**; fact survives, 3 Goal tables exist, planner CHECKs intact;
  readback + wiring on the upgraded DB → **11 passed**.
- **Migration identity preservation**: `056_user_model_facts.py`
  (revision `056`, parent `043_invocation_quota_door`) and
  `057_run_store_planner_stability.py` (revision `057`, parent `056`) are
  byte-identical to `origin/develop` (`git diff 3c761d14..HEAD` on both is
  empty); the Goal store appends as `063` with `down_revision = "062"` — a
  centrally coordinated, previously unused identity. Fresh-install
  single-head, downgrade/refusal and reapplication coverage remain inside
  the round-37 battery (code frozen).
- **Production composition**: `create_container` wires `wire_goal_store` at
  `container.py:2414` and passes it at `container.py:2701`; the Hive adapter
  builds through `create_container` (`packages/hive-conductor/backend/adapters/
  maistro_core.py:195`) and maistro-server likewise
  (`packages/maistro-server/src/maistro_server/main.py:344`); the shipped
  Container exposes the principal-carrying seam (`ScopedGoalStore`,
  `container.py:286`), proven by `test_goal_wiring.py` (green above, including
  on both installed-base-upgraded databases).
- **Convergence freeze**: `check-m1-convergence-freeze.py --base
  3c761d14db94` → exit 0 ("no unapproved new architecture island").
- **Vulture at CI argv**: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1323 = 1323; no
  ledger amendment applies in this round.

## Sole blocker — unchanged, external, re-proven first-hand

- `uv run python scripts/check-execution-lifecycles.py` (CI argv,
  quality.yml:1541) → **exit 1**, base `3c761d14db94`, candidate
  `8112c5be85e9`, 19 classified → 20 discovered, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization`.
- Ledger asymmetry re-measured: branch `quality/execution-lifecycles.json`
  carries 20 lifecycles including the one DOMAIN `GoalStatus` row (line 89);
  `git show origin/develop:quality/execution-lifecycles.json` has 19 and no
  GoalStatus row. `git ls-remote origin refs/heads/develop` still resolves to
  `3c761d14db94…` — the grant-only develop landing has not landed; no sync
  conflict exists.
- Two-merge rule re-read in source: `scripts/ratchet_provenance.py:477-495`
  — `load_authorizations` reads grants **from the base revision** ("a new
  grant does not take effect in the change that introduces it");
  `scripts/check-execution-lifecycles.py:773` passes `base=trusted_ref.base_sha`.
  The branch's own ledger row therefore cannot authorize itself by
  construction.
- Mechanical sufficiency re-proven with **no tree edit**: loading the
  unmodified gate via importlib and injecting only an in-memory GoalStatus
  grant into `_ratchet_provenance.load_authorizations`, `main()` → **exit 0**
  ("20 work-state vocabularies, all classified (3 CANONICAL, 8 CONVERGE,
  7 DOMAIN, 2 PROJECTION)"). The sole unblock is the grant-only develop
  landing, outside lane authority.
- CI test-job red reproduced with CI's argv shape:
  `pytest tests/test_check_execution_lifecycles.py -q` → **1 failed**
  (`test_the_shipped_ledger_matches_the_shipped_code`: the shipped ledger
  must gate-match shipped code against the real base) **, 28 passed** — the
  same single self-check that reds the CI `test` job and the coverage
  producer (`pytest tests/`, ci.yml:620), per the round-37 log reduction.

## Conclusion

All #1572 acceptance criteria are proven first-hand this round on the current
tree. The only red anywhere is the execution-lifecycles ratchet and its
self-check, which cannot pass from the candidate side under the two-merge
rule until develop lands the GoalStatus authorization grant-only. That action
is outside lane authority (no pushes/mutations from this lane). No code,
test, or ledger changes made; no inventory delta.
