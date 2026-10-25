# #1572 round-45 verification record (2026-10-11, head b7bf03b637800c32ae5f4ffe339cc28425bad075, base 3c761d14db94)

Repair-lane round at the round-44 head (code unchanged). This round was driven
by a fresh CI merge-queue evaluation naming the same three red jobs (`test`,
Quality gate, Coverage gate). Every driver check and every acceptance leg was
re-executed first-hand on fresh databases; the sole blocker was re-proven
external and unchanged. No code, test, or ledger changes; no inventory delta.

## Driver checks — job logs plus first-hand re-execution

| check | result |
|---|---|
| `uv sync --locked --extra dev` | ok (resolved 256, checked 214) |
| `uv run ruff check .` | All checks passed! (re-run first-hand: same) |
| `uv run ruff format --check .` | 3288 files already formatted (re-run first-hand: same) |
| driver 9-file pytest set `-q` | 161 passed, 28 skipped (re-run first-hand: 161/28 in 2.50s) |
| `check-suite-inventory.py --suite packages/maistro-core/tests` | ok, 16334 identities, 0 duplicates (re-run first-hand: ok) |

## Code freeze re-measured

`git diff --name-only e7e4d341b..HEAD` filtered to non-docs is **empty** —
`alembic/`, `packages/`, `quality/`, `scripts/`, `tests/`, `.github/` are
byte-identical to the round-37 full-battery head, so that battery carries.
Only `docs/testing/goal-1572-repair-*-roundNN.md` notes differ.

## Issue acceptance — executed first-hand this round on fresh databases

- **Goals suite, PG legs enforced on BOTH majors, fresh databases**: created
  `r45g18` (pgvector:pg18 :55712) and `r45g17` (pgvector:pg17 :55717);
  `alembic upgrade head` empty→**063** each (final step `062 -> 063, The
  canonical Goal store`), single head (`alembic heads` → `063 (head)`), and
  the catalog shows exactly the three Goal tables (`canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions`) on both majors.
  With `MAISTRO_REQUIRE_PG_LEGS=1` + `MAISTRO_TEST_PG_DSN` +
  `MAISTRO_TEST_DATABASE_URL`: `pytest packages/maistro-core/tests/goals/ -q`
  → **70 passed** on pg18 and **70 passed** on pg17. Skips become failures
  under the require flag, so this is the full conformance matrix: round-trip,
  append-only/CAS, subgoal lineage, ownership transition, cross-principal
  isolation, binding immutability, schema agreement.
- **Installed-base leg 1 (`c560d4c` → user-model `056`)**: `git archive
  c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250` to `/tmp/r45ib-c560`; fresh DB
  `r45ib18` migrated by the snapshot tree to its head **056**; representative
  rows seeded (`user_model_facts`: 2; `user_model_statement_keys`: 1);
  forward upgrade with the candidate tree ran `056 -> 057 -> … -> 062 ->
  063` with no reset and no stamp edit, ending **063 (head)**. Post-upgrade:
  both fact rows and the statement key survive unchanged, the 3 Goal tables
  exist, and both planner status CHECKs from merged `057`
  (`ck_canonical_runs_status`, `ck_canonical_node_runs_status`) are present.
  Durable-composition readback on the upgraded DB:
  `test_goal_restart_readback.py` + `test_goal_wiring.py` → **11 passed**.
- **Installed-base leg 2 (`4675101` → planner `057`)**: `git archive
  4675101647e629d290e0fece29694e43883e1395` to `/tmp/r45ib-4675`; fresh DB
  `r45ib57` migrated by the snapshot tree to its head **057**; one fact + one
  key seeded; forward upgrade `057 -> … -> 062 -> 063`, no stamp edit, ending
  **063 (head)**; fact survives, 3 Goal tables exist, planner CHECKs intact;
  readback + wiring on the upgraded DB → **11 passed**.
- **Migration identity preservation**: `git diff 3c761d14..HEAD` on
  `alembic/versions/056_user_model_facts.py` and
  `alembic/versions/057_run_store_planner_stability.py` is empty
  (byte-identical to develop); the Goal store appends as `063_canonical_goals`
  with `revision = "063"`, `down_revision = "062"` — a centrally coordinated,
  previously unused identity after the integrated develop head.
- **Production composition**: `create_container` calls `wire_goal_store` at
  `container.py:2414` and passes `goal_store=` at `container.py:2701`; the
  Container exposes the principal-carrying seam (`ScopedGoalStore`,
  `container.py:286` over the `goal_store` field `:273`); the Hive adapter
  builds through `create_container`
  (`packages/hive-conductor/backend/adapters/maistro_core.py:195`) and
  maistro-server likewise
  (`packages/maistro-server/src/maistro_server/main.py:344`); proven by
  `test_goal_wiring.py` (green above, including on both installed-base
  upgraded databases).
- **Convergence freeze**: `check-m1-convergence-freeze.py --base
  3c761d14db94` → exit 0 ("no unapproved new architecture island").
- **Vulture at CI argv**: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1323 = 1323; the
  vulture-ledger CI-repair exception does not apply (nothing to amend).
- **No closure keywords**: PR #1938 body and comments (captured dispatch
  context) contain zero `closes/fixes/resolves #…` matches; branch commit
  subjects likewise (grep over `origin/develop..HEAD` subjects: none).

## Sole blocker — unchanged, external, re-proven first-hand

- `uv run python scripts/check-execution-lifecycles.py` (CI argv,
  quality.yml:1541) → **exit 1**, base `3c761d14db94`, candidate
  `b7bf03b63780`, 19 classified → 20 discovered, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization`.
- Ledger asymmetry re-measured: branch `quality/execution-lifecycles.json`
  has 20 lifecycles including the one DOMAIN `GoalStatus` row;
  `git show origin/develop:quality/execution-lifecycles.json` has 19 and no
  GoalStatus row. The authorization file asymmetry is equally decisive:
  branch `quality/ratchet-authorizations.json` has `services.rsi::RunStatus`
  and `maistro.graph.nodes.agent_delegate_remote::DelegationStatus` but **no
  GoalStatus entry**; the base has only `services.rsi::RunStatus`.
  `git ls-remote origin refs/heads/develop` still resolves to
  `3c761d14db94…` — the grant-only develop landing has not landed; develop
  has not moved, so there is **no sync conflict** to merge.
- Two-merge rule re-read in source: `scripts/ratchet_provenance.py:477-495`
  — `load_authorizations` reads grants **from the base revision** ("a new
  grant does not take effect in the change that introduces it");
  `scripts/check-execution-lifecycles.py:773` passes
  `base=trusted_ref.base_sha`. Adding the GoalStatus grant to this branch's
  `ratchet-authorizations.json` could not authorize it by construction — and
  the branch correctly does not carry one.
- Mechanical sufficiency re-proven with **no tree edit**: pre-seeding the
  unmodified gate's cached `_ratchet_provenance` module with an in-memory
  GoalStatus grant only, `main()` → **exit 0** ("20 work-state vocabularies,
  all classified (3 CANONICAL, 8 CONVERGE, 7 DOMAIN, 2 PROJECTION)"). The
  gate itself is sound; the sole unblock is the grant-only develop landing
  of an `execution-lifecycles: maistro.goals.model::GoalStatus` record
  (owner/issue/reason), then this branch merges clean.
- CI test-job red reproduced with CI's argv shape:
  `pytest tests/test_check_execution_lifecycles.py -q` → **1 failed**
  (`test_the_shipped_ledger_matches_the_shipped_code`), **28 passed** — the
  same single self-check behind the named `test` and Coverage-gate reds
  (the coverage producer runs `pytest tests/`).

## Conclusion

All #1572 acceptance criteria are proven first-hand this round on the current
(frozen) tree. The only red anywhere is the execution-lifecycles ratchet and
its self-check, which cannot pass from the candidate side under the two-merge
rule until develop lands the GoalStatus authorization grant-only. That action
is outside lane authority (no pushes/mutations from this lane). No code,
test, or ledger changes made; no inventory delta.
