# #1572 repair — round 34 independent verification (head 9f086dad0686)

Lane L1572, job 4e40d… (4e640d7ce8724228b434997e88cc22d4). Previous round ended
with **no commit** (provider timeout after green driver checks); this round
re-executed the validation first-hand and commits the record, resolving the
no-commit block. Nothing below is taken from earlier rounds' claims without
being re-run.

## The three CI reds at 9f086dad reproduce to one external root cause

1. **Quality gate (Pillar 7)** — `RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-execution-lifecycles.py` (CI argv, quality.yml:1541) → exit 1
   with the **sole** delta: `maistro.goals.model::GoalStatus: NEW work-state
   vocabulary is absent from the trusted base and has no already-landed
   authorization`. 19 classified → 20 discovered.
2. **test job** — the shipped-ledger self-check
   `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
   (`gate.main() == 0` at :374) re-executed with `RATCHET_BASE_REV=origin/develop`
   → FAILED, captured stdout identical to (1). This is the CI test-job red.
3. **Coverage gate** — structural cascade, re-read in source: its third
   producer (quality.yml:708) runs `pytest tests/ …`, which contains the
   failing self-check, so `coverage run` exits non-zero and the `combine` step
   (quality.yml:554-575, `set -euo pipefail`) dies with "producer … contributed
   no coverage data".

Why branch-side repair is impossible: `load_authorizations` reads
`quality/ratchet-authorizations.json` **from the base revision**
(scripts/ratchet_provenance.py:482-505, docstring: "a new grant does not take
effect in the change that introduces it … two merges"). The grant file is
sha-identical on branch and base (`c43a826a5` both sides, verified via
`git rev-parse origin/develop:… HEAD:…`) and contains **zero** GoalStatus rows.
A self-grant on this branch would not be read. The sole remaining action is the
grant-only develop landing of the GoalStatus DOMAIN authorization — a GitHub
mutation outside this lane's authority.

No develop-sync conflict: `origin/develop` fetched this round, still
`435dc1937e04`.

**Vulture lane, as ordered by the repair brief:** `uv run python
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` → `1323 reviewed identities -> 1323 findings`,
unclassified 0, never_allowlist 0, **exit 0**. No ledger amendment applies.

Worktree-only red (absent from CI, re-confirmed): the regenerated
`quality/ac-state.json` is gitignored; `git status` stayed clean after every
gate run this round, and CI's own test log shows
`test_branch_independence_repository` passing.

## Acceptance criteria re-executed first-hand (head 9f086dad0686)

Fresh round-34 databases: `r34g18` on pg18.6 (`auto-1572-pg`, 127.0.0.1:55712)
and `r34g17` on pg17.11 (`auto-1572-pg17`, 127.0.0.1:55717), each migrated
empty → head **063** with plain `DATABASE_URL=… uv run alembic upgrade head`
(exit 0 both; final `alembic_version` = 063); all three tables
`canonical_goals` / `canonical_goal_revisions` / `canonical_goal_transitions`
catalog-verified on both majors.

| # | Criterion | Executed evidence this round |
|---|-----------|------------------------------|
| 1 | Goal/GoalRevision round-trip, 3 backends, shared conformance suite | `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=… uv run pytest packages/maistro-core/tests/goals -q` → **70 passed, 0 skipped on pg18 and 70 passed, 0 skipped on pg17** (memory+SQLite+Postgres legs through one parametrized suite) |
| 2 | Append-only revisions; stale refused; one CAS winner | green inside the 70/70 (`test_goal_revision_chain_is_append_only_with_one_cas_winner`, `test_concurrent_transitions_have_exactly_one_winner`) |
| 3 | Subgoal lineage; explicit recorded ownership change | green inside the 70/70 (`test_subgoal_lineage_preserves_parent_goal_and_project`, `test_agent_reassignment_is_an_explicit_recorded_transition`) |
| 4 | Run admission binds goal_id/revision; immutable; restart readback | `test_admission_binds_goal_id_and_revision`, `test_the_binding_is_immutable_after_admission` in the 70/70; `test_goal_revisions_and_bound_run_provenance_survive_a_restart` green |
| 5 | Two principals isolated; foreign Goal == missing | green inside the 70/70 (`test_two_principals_cannot_reach_each_other_s_goals`, `test_a_foreign_goal_answers_exactly_like_a_missing_one`) |
| 6 | Production composition; shipped Container exposes the store | `test_goal_wiring.py` green inside the 70/70 (`test_container_exposes_the_goal_store_and_its_seam`) |
| 7 | No second executor | `uv run python scripts/check-m1-convergence-freeze.py --base 435dc193…` → exit 0 |
| 8 | Merged 056/057 keep meaning; Goal migration appends unused id | `alembic/versions/063_canonical_goals.py` (`revision="063"`, `down_revision="062"`); identity + byte-identical-snapshot legs of `tests/migrations/test_goal_installed_base_upgrade.py` green inside the 168/168 |
| 9 | Installed-base forward upgrades from real develop snapshots, no stamp edit | `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest tests/migrations -q` → **168 passed on pg18 (3m26s) and 168 passed on pg17 (3m23s)**; `test_an_installed_base_built_by_develop_c560d4c_forward_upgrades`, `…_4675101_forward_upgrades`, `…_at_hitl_061_forward_upgrades` |
| 10 | Post-upgrade persistence, surviving planner/user-model state, durable restart readback | `test_the_upgraded_base_serves_the_durable_goal_composition` + catalog assertions, green inside both 168/168 |
| 11 | Fresh-install, single-head, downgrade/refusal coverage; per-major SHAs/commands/results | `test_migration_chain.py`, single-head legs green inside both 168/168; exact SHAs (base 435dc193, head 9f086dad), commands and results in this table; skipped legs = 0 (`MAISTRO_REQUIRE_PG_LEGS=1`), unexecuted = none |

Acceptance-state gate at CI argv: `MANDATE_BASE_SHA=435dc193… uv run python
scripts/check-ac-state.py --run-tests --ratchet --mandate 435dc193…` with both
PG vars → `OK: every criterion this change declares is proven.`, mandate
report all zeros, **exit 0**.

## Gates re-run green this round (ruling out a second branch-side red)

ruff check `.` clean; ruff format `--check` 3288 files formatted; radon 137 →
137 exit 0; reachability exit 0; wiring-reads ledger matches; durable-table
112 tables declared exit 0; workflow-inventory 28 dispositioned clean;
promotion-surface ok; xenon at CI argv (9 packages, `-i third_party`) →
block=0 average=0 module=0 vs baseline 145, empty module ledger;
`uv run mypy --strict` over all seven shipped package src trees → `Success: no
issues found in 899 source files` (a core-only scoping surfaces 5
`maistro_bootstrap` import-not-found artifacts of this venv in two files the
branch does not touch); suite-inventory 16334 unique identities, 0 duplicates.

## Disposition

Unchanged from rounds 28–33, now re-proven at the current head with fresh
round-34 databases: all 11 acceptance criteria are executed and green on both
supported PostgreSQL majors; the three red merge-queue checks share the single
external root cause (GoalStatus authorization must land on develop before the
branch carrying the classification can pass the two-merge ratchet). No code,
no tests, no ledger edits, no inventory delta this round — this file is the
round record.
