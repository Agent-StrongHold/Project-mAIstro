# #1572 round-50 independent verification at 0df39d8561d6 (2026-10-11)

Verifier/writer round. Base 3c761d14db944a727fa0744444bc67cfe36d49f7
(`git fetch` + `git ls-remote` this round — unchanged, no sync conflict to
merge), head 0df39d8561d674e78605830b5e83fd8d040f4213, tree clean at start.
No code, test, ledger or workflow edits made; no inventory delta (no suites
changed). This note is the round's only artifact, committed per the writer
rule. The prior job (3a2afc63) died on a provider timeout *after* its four
deterministic checks all returned 0; those logs were read and every
load-bearing leg below was additionally re-executed first-hand this round.

## Driver checks (job c655449389434b629514aa45bd7e6972) — all green

- `uv sync --locked --extra dev` ok; `uv run ruff check .` ok ("All checks
  passed!"); `uv run ruff format --check .` — 3288 files formatted.
- Driver 9-file pytest set: **161 passed, 28 skipped** (skips are the PG legs,
  executed with enforced legs below).
- `check-suite-inventory.py --suite packages/maistro-core/tests` — ok, 16334
  unique identities, 0 duplicates.

## Sole blocker — re-proven external, first-hand this round

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) — **exit 1**, sole finding: `maistro.goals.model::
  GoalStatus: NEW work-state vocabulary is absent from the trusted base and
  has no already-landed authorization` (19 classified -> 20 discovered; the
  gate itself prints `baseline: base 3c761d14db94`).
- CI `test` red reproduced first-hand: `uv run pytest
  tests/test_check_execution_lifecycles.py -q` -> **1 failed / 28 passed**,
  `test_the_shipped_ledger_matches_the_shipped_code`
  (tests/test_check_execution_lifecycles.py:374, `assert gate.main() == 0`)
  with the identical GoalStatus stdout. This meta-test is also the Coverage
  gate's pytest producer, explaining both remaining CI reds.
- Ledger facts (read via `git show` / `git diff --numstat origin/develop --
  quality/` on both refs): branch `quality/execution-lifecycles.json` banks
  `maistro.goals.model::GoalStatus` (DOMAIN, rationale naming #1572); base has
  19 rows, no GoalStatus. `quality/ratchet-authorizations.json` on **both**
  branch and base contains only the #1136 RunStatus/DelegationStatus grants
  under `execution-lifecycles` — no GoalStatus grant anywhere. The branch's
  only quality deltas vs develop are ac-state lane notes, the new
  durable-table-retention rows, and the GoalStatus classification itself.
- Two-merge rule re-read in source this round:
  `scripts/ratchet_provenance.py:478-505` — `load_authorizations` resolves the
  authorizations file **from the base revision** ("a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now
  two merges"); `scripts/check-execution-lifecycles.py:773,783-784` —
  `authorized` is loaded with `base=trusted_ref.base_sha` and
  `_unauthorized_additions` requires a base-side grant or `visible_at_base`
  (`_discover_at_revision` shows GoalStatus does not exist at base).
- **Mechanical sufficiency re-proven with no tree edit**: the real
  `ratchet_provenance.py` and real `check-execution-lifecycles.py` modules
  were loaded unmodified (importlib, private module names) with only an
  in-memory `execution-lifecycles: maistro.goals.model::GoalStatus` grant
  added to `load_authorizations`'s result — unmodified gate `main()` returned
  **0** (`OK: 20 work-state vocabularies, all classified (3 CANONICAL,
  8 CONVERGE, 7 DOMAIN, 2 PROJECTION)`); `git status` clean afterwards.
  The branch content is correct; the only missing input is the base-side
  grant.

## Why this is not resolvable in-lane (unchanged from round 49)

An in-branch `ratchet-authorizations.json` grant is structurally unread
(base-resolved provenance above) and would be exactly the self-authorization
the provenance module exists to prevent. Removing the GoalStatus row from the
candidate ledger fails `audit` (candidate must classify what the scanner
found). Re-expressing the Goal's desired-state lifecycle as RunStatus would
misrepresent the model the issue mandates (a Goal never drives a scheduler;
DOMAIN is the honest classification). Hiding the enum from the scanner would
be gate evasion, not compliance. Landing the grant on develop requires a
GitHub mutation, which this lane is prohibited from performing.

**Unblock (external, one merge):** land on develop a
`quality/ratchet-authorizations.json` grant for
`execution-lifecycles: maistro.goals.model::GoalStatus` (owner/issue #1572/
reason — the DOMAIN rationale is ready to reuse). After that lands, this
branch merges green with **zero further changes** (mechanically proven above).

## Acceptance re-executed first-hand this round

- **Fresh install, pg18.6**: created empty `r50g18` (container
  `auto-1572-pg`, 127.0.0.1:55712); `alembic upgrade head` empty -> **063**,
  final step `062 -> 063, The canonical Goal store`; catalog shows exactly
  `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`; `alembic_version` = 063; `alembic heads` =
  single head `063`; `063_canonical_goals.py` has `revision = "063"`,
  `down_revision = "062"`;
  `git diff origin/develop HEAD -- alembic/versions/056* 057*` empty
  (merged user-model `056` and planner `057` identities preserved).
- **Goals + durable-events suite, PG legs enforced, pg18**:
  `MAISTRO_REQUIRE_PG_LEGS=1` + both DSN vars plain `postgresql://`
  (`MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`) against `r50g18`:
  `pytest packages/maistro-core/tests/goals
  packages/maistro-core/tests/events/test_container_pg_durable_events.py -q`
  -> **77 passed, 0 skipped** (all three backend conformance legs, CAS/
  append-only, Subgoal lineage, cross-principal isolation, Run-binding
  immutability, schema agreement, restart readback — no silent skips).
- **Fresh install, pg17.11**: created empty `r50g17` (container
  `auto-1572-pg17`, 127.0.0.1:55717); `alembic upgrade head` empty -> 063,
  3 Goal tables, single head; goals suite with enforced PG legs -> **70
  passed, 0 skipped**. Both supported majors green this round.
- **Installed-base leg 1 (`c560d4c` -> user-model `056`)**: `git archive
  c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250` to `/tmp/r50ib-c560`; fresh DB
  `r50ib18` migrated by the snapshot tree to its head **056** (via
  `043_invocation_quota_door`, ancestry preserved); seeded 2
  `user_model_facts` rows + 1 `user_model_statement_keys` row; forward
  upgrade with the candidate tree ran `056 -> 057 -> ... -> 062 -> 063` with
  no reset and no stamp edit, ending **063**. Post-upgrade: both fact rows and
  the statement key survive, the 3 Goal tables exist, and both planner status
  CHECKs from merged `057` (`ck_canonical_runs_status`,
  `ck_canonical_node_runs_status`) are present. Durable-composition readback
  on the upgraded DB: `test_goal_restart_readback.py` + `test_goal_wiring.py`
  -> **11 passed**.
- **Installed-base leg 2 (`4675101` -> planner `057`)**: `git archive
  4675101647e629d290e0fece29694e43883e1395` to `/tmp/r50ib-4675`; fresh DB
  `r50ib57` migrated by the snapshot tree to its head **057**; one fact + one
  key seeded; forward upgrade `057 -> ... -> 062 -> 063`, no stamp edit,
  ending **063**; fact/key survive, 3 Goal tables, planner CHECKs intact;
  readback + wiring -> **11 passed**.
- **Supported downgrade + reapplication** (fresh `r50g18`):
  `alembic downgrade 062` removes exactly the 3 Goal tables (0 remain) and
  `alembic upgrade head` reapplies them (3 present, version 063).
- **Convergence freeze**: `check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` (CI argv per
  formal-conformance.yml:77) -> **exit 0** ("no unapproved new architecture
  island") — no `GoalRun`/`OrchestratorRun`/second executor.
- **Vulture at CI argv**: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> **exit 0**, `1323
  reviewed identities -> 1323 findings`; no amendment applies (the vulture
  ledger is not the red gate; execution-lifecycles is).
- **Production composition re-read in source**: `container.py:44` imports
  `wire_goal_store`, `:2414` calls it inside `create_container`, `:2701`
  passes `goal_store=`, `:273` the `goal_store` field, `:277-286` the
  principal-carrying `goal_reader` -> `ScopedGoalStore` seam (foreign Goal
  indistinguishable from missing); Hive builds through `create_container`
  (`packages/hive-conductor/backend/adapters/maistro_core.py:195`);
  maistro-server likewise (`packages/maistro-server/src/maistro_server/
  main.py:344`). Proven by `test_goal_wiring.py` (green above, including on
  both installed-base upgraded databases).
- **Code identity**: `git diff e7e4d341b6b71b0483dd50d2203fbca8cea531db..HEAD`
  touches only `docs/testing/` round notes (13 files, 0 non-docs files), so
  the fully-batteried code state is unchanged since round 37.
