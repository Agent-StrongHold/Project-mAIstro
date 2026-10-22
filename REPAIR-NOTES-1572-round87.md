# #1572 round-87 repair verification (dispatch head d3208930376f)

All claims below were re-executed first-hand at HEAD `d3208930376f53c637429ffb8216dffc9f453f77`
(clean tree, exactly the dispatch head; base `3c761d14db944a727fa0744444bc67cfe36d49f7`).
Nothing was assumed from rounds 74-86; each crux was re-derived by execution this round.

## External state (unchanged, re-fetched this round)

- `git fetch origin` clean; `origin/develop` = `3c761d14db94` == merge-base of HEAD. Branch is 188 commits ahead; develop has not moved.
- `git ls-remote`: `refs/pull/1938/head` = `2f5dd46969fc` (still unmerged; the `refs/pull/1938/merge` ref is GitHub speculation, not merge evidence). develop = `3c761d14db94`.
- `git grep GoalStatus origin/develop -- quality/` → no matches (0 grants on the base).
- `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` → 0 lines; the branch file carries 0 GoalStatus entries. The grant exists only inside unmerged PR #1938.

## The block (re-proven by execution, not inherited)

1. `uv run python scripts/check-execution-lifecycles.py` (exact CI argv, `.github/workflows/quality.yml:1541`, no args) → **EXIT 1**, sole finding:
   `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base and has no already-landed authorization` (19 classified → 20 discovered; baseline base = `3c761d14db94`).
2. `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**; the failing test `test_the_shipped_ledger_matches_the_shipped_code` reproduces the gate's stdout verbatim (same sole finding, same base). This is the merge-queue `test: failure`, 1:1.
3. Gate mechanics re-read from source: `scripts/check-execution-lifecycles.py:773` calls `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` and `:783` discovers at the base revision. An in-branch grant is a structural no-op (see 0-line diff above); `RATCHET_BASE_REV=HEAD` is refused by `_refuse_self_reference` (rounds 77/81 executed simulations: develop+grant-only parent → gate EXIT 0 with zero branch edits; same tree on plain develop → EXIT 1).
4. The candidate is correctly classified: `quality/execution-lifecycles.json` carries the DOMAIN entry for `maistro.goals.model::GoalStatus` with a rationale distinguishing desired-state accountability from the canonical Run/NodeRun/Attempt spine. Classification is not the defect; the missing **base** grant is.
5. `GoalStatus` is issue-mandated (`packages/maistro-core/src/maistro/goals/model.py:52-72`): `ACTIVE` plus terminal `SATISFIED/CANCELLED/FAILED/SUPERSEDED`, terminal-final, CAS-gated transitions — exactly the issue's lifecycle bullet. Removal/rename or a stringly-typed dodge would be prohibited weakening.
6. Lane-brief vulture CI-repair path checked at the exact argv (`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → **EXIT 0**, 1323 reviewed = 1323 findings, `unclassified: 0`, `never_allowlist: 0`. **No amendment target exists**; the permitted vulture-ledger exception does not apply to this failure (the failing gate is execution-lifecycles, not vulture).

Conclusion: **no in-branch repair exists.** The sole resolution is the maintainer landing the
grant hunk on develop (merge grant-only PR #1938 or an equal grant-first PR), after which the
gate and the shipped-ledger test pass at this tree with zero branch edits.

## Acceptance criteria — re-executed at this head

Fresh isolated `pgvector/pgvector:pg18` container `goals_r87` (port 15487), fresh databases
`goals_r87` (primary) and `goals_r87_mig` (migration fixtures); container removed afterwards.

- **AC1 three-backend conformance round-trip** — `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=… uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed / 0 skipped** in 5.37s (in-memory, SQLite and PostgreSQL legs live through the shared conformance suite; sqlite/pg catalogue parity via `test_goal_pg_schema_agreement.py` inside the 70).
- **AC2 append-only revisions, stale-revision refusal, CAS one winner** — inside the 70 (`test_goal_store_conformance.py`).
- **AC3 subgoal lineage preserves parent/Project; owning-Agent change is an explicit recorded transition** — inside the 70 (`canonical_goal_transitions` exercised).
- **AC4 Run admission binds `goal_id`/`goal_revision`; immutable after admission** — `test_run_goal_binding.py` inside the 70, executed against the migrated PostgreSQL DB.
- **AC5 two principals in two Workspaces isolated; foreign Goal indistinguishable from missing** — inside the 70.
- **AC6 production composition wires the store; a test proves the shipped Container exposes it** — source-read `packages/maistro-core/src/maistro/container.py:44` (import), `:271-276` (`goal_reader` ScopedGoalStore seam), `:2412-2414` (`wire_goal_store` inside `create_container`); `goals/wiring.py:33-34`; `test_goal_wiring.py` inside the 70.
- **AC7 no GoalRun / OrchestratorRun / second executor / product-private lifecycle** — `grep -rn "GoalRun\|OrchestratorRun" packages/ alembic/ --include=*.py` → exit 1 (absent); exact CI argv `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94` (`.github/workflows/formal-conformance.yml:77`) → **EXIT 0** ("no unapproved new architecture island").
- **Migration identity (2026-10-06 clarification)** — `alembic/versions/063_canonical_goals.py`: `revision = "063"`, `down_revision = "062"` (appended after the integrated develop head; centrally coordinated new identity). Merged identities un-reassigned at source: `056_user_model_facts` (`down_revision = "043_invocation_quota_door"`, merged in c560d4c) and `057_run_store_planner_stability` (`down_revision = "056"`, merged in 4675101). Fresh-install upgrade on empty DB: `DATABASE_URL=… uv run alembic upgrade head` → **EXIT 0**, chain ran `…057 -> 058 … 062 -> 063, The canonical Goal store…`, single head `063`; psql shows exactly `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` and `alembic_version = 063`.
- **Installed-base upgrade fixtures** — `MAISTRO_TEST_DATABASE_URL=… uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -q` → **26 passed** in 75.9s on the real pg18 server: forward upgrades from the actual pre-Goal develop snapshots (c560d4c→056, 4675101→057) without stamp edits, plus fresh-install/single-head/unique-ID/downgrade-refusal/reapplication coverage.
- **Restart readback** — `test_goal_restart_readback.py` inside the 70 (re-open the durable composition, read back Goals/revisions and bound Run provenance).
- **Lint/suite drivers** — `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .` → 3288 files clean; driver logs `check-*.log` green at this head (uv sync resolved, targeted suite 161 passed/28 skipped, suite inventory `ok … 16334` identities).

## Operator record

- Goals PG legs need **both** `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`, plain
  `postgresql://` DSNs (the asyncpg legs construct pools directly), against an already-migrated
  database; the installed-base tests build their own populated fixture databases on the same
  server from the snapshot commits (shallow clones skip those legs).
- Local-only, not a branch defect: `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
  fails in this worktree via untracked, gitignored `quality/ac-state.json` (`.gitignore:81`);
  left untouched.

## Verdict

**BLOCKED** — unchanged, and only externally resolvable: merge the grant-carrying PR #1938
(owner @BlakeMatthews-dev, issue #1572) into develop, then this branch passes the
execution-lifecycles gate and the shipped-ledger test with zero branch edits.

Docs-only commit (this file): no code, test, or ledger changes; no suite-inventory delta.
