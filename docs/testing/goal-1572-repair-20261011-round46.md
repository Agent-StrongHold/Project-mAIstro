# #1572 round-46 repair verification (2026-10-11)

Head at start: `d1feb9fb1` (round-45 verification commit); base `3c761d14db94`.

## Carry-over proof

`git diff e7e4d341b..HEAD` filtered to non-docs (`packages/`, `scripts/`,
`tests/`, `quality/`, `docs/adr/`, `alembic/`) is **empty** — the candidate code
is byte-identical to the round-37 full-battery head `e7e4d341b`, so that battery
carries. Only `docs/testing/goal-1572-repair-*-roundNN.md` notes differ.

## Driver deterministic checks (this job, first-hand + logs)

`check-0..check-4` all green: `uv sync --locked --extra dev` ok; `ruff check .`
→ All checks passed; `ruff format --check .` → 3288 files formatted; driver
9-file pytest set → 161 passed / 28 skipped; `check-suite-inventory.py` → ok,
16334 identities match the recorded inventory.

## Issue acceptance — re-executed first-hand this round

- **Fresh goals leg, PG enforced (pg18)**: created `r46g18` on
  `auto-1572-pg` (:55712, pgvector:pg18 / PG 18.6); `DATABASE_URL=…r46g18
  uv run alembic upgrade head` migrated empty → **063**, final step
  `062 -> 063, The canonical Goal store`, `alembic heads` → `063 (head)`
  (single head); catalog shows exactly `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions`. With
  `MAISTRO_REQUIRE_PG_LEGS=1` + `MAISTRO_TEST_PG_DSN` +
  `MAISTRO_TEST_DATABASE_URL`: `pytest packages/maistro-core/tests/goals/ -q`
  → **70 passed** (skips become failures under the require flag, so this is
  the full conformance matrix: round-trip, append-only/CAS, subgoal lineage,
  ownership transition, cross-principal isolation, binding immutability,
  schema agreement). Without the PG env the same suite gives 48 passed /
  22 skipped (memory/sqlite legs only).
- **Migration identity**: `git diff 3c761d14..HEAD` on
  `alembic/versions/056_user_model_facts.py` and
  `alembic/versions/057_run_store_planner_stability.py` is empty
  (byte-identical to develop); `063_canonical_goals.py` declares
  `revision = "063"`, `down_revision = "062"` (pure append).
- **Production composition**: `container.py` — `ScopedGoalStore` seam (~:286),
  `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` (~:2414),
  `goal_store=goal_store` passed into the assembled container (~:2701);
  Hive `packages/hive-conductor/backend/adapters/maistro_core.py:195` and
  maistro-server `main.py:344` both compose through `create_container`.
- **Installed-base legs** (c560d4c→056 / 4675101→057 snapshots, forward
  upgrade with facts/keys surviving, readback 11/11): executed first-hand in
  rounds 44 and 45 on `r45ib18`/`r45ib57`; carried here by the byte-identity
  proof above (no migration, model, or store file changed since).

## Gates

- `check-m1-convergence-freeze.py --base 3c761d14…` → **exit 0**
  ("no unapproved new architecture island"); `GoalStatus` is classified
  DOMAIN in the ledger — desired-state vocabulary, not a second execution
  spine.
- Vulture at CI argv (`quality.yml:1079`):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**,
  1323 reviewed identities = 1323 findings; no unbanked identities, no
  ledger amendment applies in this round.
- Suite inventory: driver check-4 → ok, 16334 identities.

## Sole blocker — re-proven first-hand, unchanged and external

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  `quality.yml:1541`) → **exit 1**:
  `19 classified lifecycles -> 20 discovered lifecycles`, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization`.
- `git ls-remote origin develop` → still `3c761d14db94…` — the grant-only
  GoalStatus authorization has **not** landed on develop; no sync conflict.
- Two-merge mechanics re-read in source this round: authorizations are read
  from the merge base (`scripts/ratchet_provenance.py:477-495`,
  `scripts/check-execution-lifecycles.py:773`), so the branch ledger row at
  `quality/execution-lifecycles.json` (GoalStatus DOMAIN, with rationale)
  and any candidate-side `ratchet-authorizations.json` edit structurally
  cannot authorize it ("candidate baseline edits cannot approve them").
  Mechanical sufficiency was proven in rounds 42–45 with no tree edit:
  an in-memory GoalStatus grant makes the unmodified gate `main()` exit 0
  (20/20 classified).
- The named CI reds are this single root cause: `tests/
  test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  re-run first-hand → 1 failed / 28 passed (the test drives the unmodified
  gate `main()` against the real base); the Quality and Coverage gate reds
  are the same failure surfaced by the gate job.

## Process hygiene

- No closure keywords: the only regex matches in the dispatch context are
  negations ("does **not** close the issue"), unrelated PR bodies
  (#861/#854/#131/#1047), role-prompt text, and patch boilerplate;
  PR #1938 remains **open** ("WIP: [M1] Implement the canonical Goal
  store…"); no GitHub mutation performed or requested.
- No code, test, or ledger changes this round; no inventory delta.
- Verdict: **BLOCKED** — candidate complete and green except the one
  two-merge gate whose only unblock is a grant-only
  `execution-lifecycles: maistro.goals.model::GoalStatus` authorization
  landing on develop, outside lane authority (no push/mutation permitted).
  Once landed, this branch merges with no further change.
