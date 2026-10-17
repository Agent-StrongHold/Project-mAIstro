# #1572 round-68 repair verification (2026-10-12, dispatch head `7ee52d4e6ab8`)

Verifier instruction for this round: "Do not assume earlier verification claims are
true. Check every acceptance criterion against reachable production behavior and
meaningful tests." Every claim below was re-derived first-hand this round at the
dispatch head; nothing was carried from round 67's notes except where explicitly
marked. The driver's own checks (job `044bf1629beb45f8b`) are green: ruff check
("All checks passed!"), ruff format (3288 files clean), focused 9-file pytest set
161 passed / 28 skipped, suite inventory ok (16334 identities).

## 0. Tree identity

- `git rev-parse HEAD` = `7ee52d4e6ab8c5d2c57b0a8d35f6d4412c928c54` (dispatch head).
- `git diff --stat db091060d..HEAD -- packages scripts quality` is **empty**: the
  tree is code-identical to the round-58..62 battery tree. Only docs/testing
  round reports were added since.
- `git fetch origin` re-run this round: no new objects; `origin/develop` =
  `3c761d14db944a727fa0744444bc67cfe36d49f7` == `git merge-base HEAD origin/develop`.
  **Nothing to merge; no GoalStatus grant has landed on develop.**

## 1. The blocker, re-derived first-hand (not assumed)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  `quality.yml:1541`) → **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 classified → 20
  discovered). Baseline printed: base `3c761d14db94` (== origin/develop).
- `uv run pytest tests/test_check_execution_lifecycles.py` → **1 failed / 28
  passed**; the failed test is
  `test_the_shipped_ledger_matches_the_shipped_code`, asserting `main() == 0`
  with the identical sole finding. This is the merge-queue `test: failure`; the
  coverage `combine` step inherits the dead producer (no independent deficit).
- Source re-read this round:
  - `scripts/ratchet_provenance.py:478` `load_authorizations` reads the grant
    file **from the base revision**; its docstring states the consequence
    verbatim: "a new grant does not take effect in the change that introduces
    it. Authorizing a floor-raise is now two merges."
  - `resolve_baseline` (`:301`) precedence: explicit arg > `RATCHET_BASE_REV` >
    GitHub event base > `origin/develop`; `_refuse_self_reference` (`:258`)
    refuses a base that is HEAD itself.
  - `_discover_at_revision` does `git show {base_sha}:{path}` of the candidate
    module paths. `git cat-file -e 3c761d14db94:packages/maistro-core/src/maistro/goals/model.py`
    → exit 128: **the module does not exist at the base** (it is new in this
    branch), so base visibility is impossible for `GoalStatus`.
  - `_unauthorized_additions` (`:705`) keeps the candidate's own ledger
    classification from self-authorizing an addition.
- Empirical: `git diff origin/develop HEAD -- quality/ratchet-authorizations.json`
  is **0 lines** (byte-identical); the file carries exactly the two #1136 grants
  (`services.rsi::RunStatus`, `agent_delegate_remote::DelegationStatus`) on both
  sides. `git grep GoalStatus origin/develop -- quality/` → no matches. An
  in-branch grant is therefore a proven no-op (also observed empirically in
  rounds 59–60: adding it did not turn the gate green; it was removed again).
- Issue comments re-scanned from dispatch-context.json (380 comments, newest
  `2026-10-12T12:14:15Z`): newest entries are bot progress markers
  (started/blocked) only — **no maintainer authorization/grant marker**.
- Lane-brief "CI GATE REPAIR (vulture exact-debt-ledger)" exception has **no
  target**: `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv,
  `quality.yml:1079`) → **exit 0**, 1323 reviewed = 1323 findings, unclassified 0.
- No legitimate in-branch repair exists: removing/renaming the `GoalStatus`
  vocabulary would violate the issue's mandated desired-state lifecycle
  (ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED, with CAS transitions the
  shipped conformance suite exercises) or dodge the `_MIN_WORK_STATES` detector;
  editing the gate is prohibited weakening. The required action is external:
  a maintainer lands an `execution-lifecycles` grant for
  `maistro.goals.model::GoalStatus` on develop (the #1833 two-merge precedent),
  then this branch merges develop — after which the gate and the shipped-ledger
  test pass with **zero edits** to this branch.

## 2. Acceptance criteria, executed first-hand this round

Environment: pgvector/pg18 container `maistro-postgres` (127.0.0.1:5433), fresh
databases `r68g18` (migrated), `r68ib18`, `r68chain` created for this round.
`MAISTRO_REQUIRE_PG_LEGS=1` set for the goals suite so a skipped PG leg fails
instead of silently passing.

- **AC1 (round-trip on all three backends)** —
  `test_goal_round_trips_through_the_backend[memory|sqlite|postgres]` inside
  `uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed
  / 0 skipped**.
- **AC2 (append-only; stale refused; one CAS winner)** —
  `test_goal_revision_chain_is_append_only_with_one_cas_winner[*]`,
  `test_lifecycle_transitions_cas_and_terminal_is_final[*]`,
  `test_concurrent_transitions_have_exactly_one_winner[*]` — all passed in the
  same run.
- **AC3 (subgoal lineage; explicit recorded agent transition)** —
  `test_subgoal_lineage_preserves_parent_goal_and_project[*]`,
  `test_agent_reassignment_is_an_explicit_recorded_transition[*]`,
  `test_goal_cannot_be_its_own_parent` — passed.
- **AC4 (Run admission binding, immutable after admission)** —
  `test_run_goal_binding.py` (admission binds `goal_id`/`goal_revision`,
  binding immutable, unset without a goal) — passed with PG leg required.
- **AC5 (workspace isolation; foreign == missing)** —
  `test_two_principals_cannot_reach_each_other_s_goals[*]`,
  `test_a_foreign_goal_answers_exactly_like_a_missing_one[*]` — passed.
- **AC6 (production composition wires the store)** —
  `test_goal_wiring.py::test_container_exposes_the_goal_store_and_its_seam` passed;
  source re-read first-hand: `container.py:44` imports, `:276/:286` the
  `goal_reader` seam (`ScopedGoalStore`), `:2414` `wire_goal_store(...)` inside
  `create_container`; `maistro_server/main.py:29,344` builds that Container;
  Hive `backend/adapters/maistro_core.py:148,195` calls the same
  `create_container`.
- **AC7 (no second executor / product-private Goal lifecycle)** —
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db944…`
  (CI argv, `formal-conformance.yml:77`) → **exit 0**.
- **Migrations** — `uv run alembic upgrade head` on empty `r68g18` → single
  chain ending `062 -> 063, The canonical Goal store`; `alembic heads` → `063
  (head)` only; after upgrade `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions` all present (queried via asyncpg); downgrade
  `063 -> 062` drops them (3 → 0), re-upgrade restores (0 → 3).
- **Installed-base boundary** — `uv run pytest
  tests/migrations/test_goal_installed_base_upgrade.py -q` on fresh `r68ib18`
  → **8 passed** (identity/ancestry of merged `056`/`057` preserved; provenance
  byte-identical to the `c560d4c`/`4675101` snapshots; actual develop-snapshot
  databases forward-upgrade to the candidate head with no stamp edit; facts,
  keys and a Run survive; planner indexes/CHECK intact; Goal composition
  persists and reads back on the upgraded schema).
- **Migration chain** — `uv run pytest tests/migrations/test_migration_chain.py
  -q` on fresh `r68chain` → **18 passed**.
- **Restart readback** — `test_goal_revisions_and_bound_run_provenance_survive_a_restart`
  passed (in the 70).
- **Typecheck** — `uv run mypy packages/{maistro-core,maistro-server,maistro-turing,maistro-canvas,maistro-bootstrap,maistro-registry,maistro-ext-sdk}/src`
  → **Success: no issues found in 899 source files**.
- Carried by code-identity (tree identical to `db091060d` where rounds 58–67
  executed them; not re-run this round): events+runs suites (1888p/3s), pg17
  legs, full core suite.

## 3. Operational note for future rounds (DSN pitfalls hit this round)

- `MAISTRO_TEST_DATABASE_URL` must be a **plain** `postgresql://` URL for
  `test_goal_pg_schema_agreement.py` (it hands the value straight to asyncpg;
  `postgresql+asyncpg://` fails with `scheme is expected to be either
  "postgresql" or "postgres"`).
- The host-side role password is the **container's `POSTGRES_PASSWORD`**
  (retrievable via `docker exec maistro-postgres sh -c 'echo -n
  "$POSTGRES_PASSWORD"'`), URL-encoded into the DSN. Two traps: (a) `psql`
  inside the container succeeds with any password because its socket/local
  pg_hba is `trust` — that "AUTH-OK" is a false positive; (b) the repo `.env`
  `DB_PASSWORD` value has surrounding/inner whitespace and does **not** match
  the role password. Verified from the host: wrong passwords are refused with
  `InvalidPasswordError`, the container password connects.

## 4. Local-only failure (unchanged, left untouched)

`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
fails in this worktree only, caused by the untracked gitignored scratch file
`quality/ac-state.json` (2026-10-11) found by the unconditional rglob in
`scripts/check-branch-independence.py:206`. CI passed it. The file is prior
salvage and was left untouched.

## 5. Verdict

**BLOCKED** — identical to rounds 58–67: the only failing gate evidence is the
external `execution-lifecycles` authorization for `maistro.goals.model::GoalStatus`,
which by design (`ratchet_provenance.load_authorizations` reads the base) cannot
be satisfied inside this branch. All seven issue acceptance criteria plus the
migration/installed-base closure boundary are proven by executed tests above;
the "authorization" closure-boundary item is the single unproven criterion and
is external. After the maintainer lands the grant on develop and this branch
merges develop, the gate and `test_the_shipped_ledger_matches_the_shipped_code`
pass with zero further edits.

Docs-only change; no code, test, or ledger edits; no inventory delta (no tests
added or removed — goals suite collected the same identities).
