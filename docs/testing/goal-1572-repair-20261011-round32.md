# #1572 verification round 32 (job 114e8b27e64e4c948f623cc87d909ca0) — independent re-verification at 2208337b8dd2; every acceptance leg re-executed first-hand on fresh round-32 databases

Head: `2208337b8dd2c1a0654fe80da7dcc3efdfe0d5c6` (= dispatch head; the only delta over the verified code head `7643681b5c14` is this docs series — `git diff --name-only 7643681b..2208337b` is `docs/testing/goal-1572-repair-20261011-round31.md` alone), base: `435dc1937e0407ab4de198ffcced49860bb14ad2`. No prior-round claim trusted without re-execution; every command below was run this round. No source, test, workflow, ledger or grant file touched — verification-only round.

## Driver checks (check-0..check-4.log in the job directory)

All five green at this head: `uv sync --locked --extra dev`; `ruff check .` ("All checks passed!"); `ruff format --check .` (3288 files already formatted); focused Goal/parity pytest **161 passed, 28 skipped** (the 28 PG-leg skips re-executed below with legs enforced); `check-suite-inventory.py --suite packages/maistro-core/tests` → ok, **16334** unique nodes, 0 duplicates.

## The merge-queue reds — each re-executed first-hand at this head

1. **Quality gate — failing step reproduced at CI's exact argv.** `uv run python scripts/check-execution-lifecycles.py` → **exit 1**: `19 classified lifecycles -> 20 discovered`, sole delta `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base and has no already-landed authorization` (baseline printed `base 435dc1937e04`, `candidate 2208337b8dd2`). The branch's `quality/ratchet-authorizations.json` is **sha256-identical to `origin/develop`'s** (`2f7b95dc…`; develop re-checked at `435dc1937e04`, still unmoved) and the branch diff does not touch the grant file — consistent with the two-merge rule (`load_authorizations` reads the grant file from the merge base, `scripts/ratchet_provenance.py:474-486`; AGENTS.md "A floor raise takes two merges"): no on-branch grant edit can authorize the branch's own vocabulary. The branch ledger banks GoalStatus DOMAIN (`quality/execution-lifecycles.json`, +4 rows) — banking is not authorizing.
2. **`test` job red — same sole root cause, reproduced.** `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**, the failure being `test_the_shipped_ledger_matches_the_shipped_code` with the **identical GoalStatus delta**. The other root-suite red is the gitignored worktree-only `quality/ac-state.json` byproduct (`.gitignore:81`; branch diff touches only `quality/execution-lifecycles.json` and durable-table notes, never the grant file or ac-state) — a CI checkout sees exactly one red: the external grant gap. The one additional red round 31 saw once (`test_property_substrate.py`) did not reproduce here and remains an untouched-file flake, not an acceptance criterion.
3. **Coverage gate — structural cascade re-read from workflow source.** quality.yml's `combine` step (`set -euo pipefail`, lines 554–575) exits 1 when a producer writes no `.coverage`; the scripts producer (line 713) re-runs `pytest tests/ …` before `coverage xml`, so the shipped-ledger self-check failure aborts it under the fail-fast shell. The coverage red carries zero independent signal.

## Acceptance criteria — re-executed first-hand this round, on fresh databases

Fresh databases created this round on the lane servers: `r32wg18` (pg18, `auto-1572-pg` 127.0.0.1:55712) and `r32wg17` (pg17, `auto-1572-pg17` 127.0.0.1:55717), each migrated **empty → `063`** with `uv run alembic upgrade head` (DATABASE_URL); all three Goal tables (`canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`) verified present by direct catalog query on both majors; stamp `063` confirmed; throwaway `r32wib18`/`r32wib17` for the installed-base suites.

- **Fail-loud re-proven live first:** with `MAISTRO_REQUIRE_PG_LEGS=1` and no DSN, the store legs raise `RuntimeError` (`test_goal_store_conformance.py:141`: "cannot run and must not be silently skipped") — the PG legs cannot hide as skips.
- **3-backend round-trip via shared conformance suite:** `MAISTRO_REQUIRE_PG_LEGS=1` + DSN vars → `uv run pytest packages/maistro-core/tests/goals -q` → **70 passed pg18** and **70 passed pg17**.
- **Append-only revisions, stale-refused, one concurrent winner** (`test_goal_revision_chain_is_append_only_with_one_cas_winner` et al.), **Subgoal lineage + recorded ownership change**, **cross-Workspace isolation with foreign Goal ≡ missing** (`test_a_foreign_goal_answers_exactly_like_a_missing_one`), **Run binding immutable after admission** (`test_run_goal_binding.py`), **shipped-wiring proof** (`test_goal_wiring.py`): all inside the 70/70, both majors.
- **Production composition wired (Hive and maistro-server):** source read this round — `packages/maistro-core/src/maistro/container.py:44` (import), `:2414` (`goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` in `create_container`), `:2701` (constructor arg), `:273` (field), `:286` (`ScopedGoalStore` seam over the #1150 authorization path); Hive `backend/adapters/maistro_core.py:195`; maistro-server `main.py:344`.
- **No `GoalRun`/`OrchestratorRun`/second executor/product-private lifecycle:** `check-m1-convergence-freeze.py --base 435dc1937e0407ab4de198ffcced49860bb14ad2` → "no unapproved new architecture island", **exit 0**.
- **Migration identity / installed-base boundary — full directory this round:** `MAISTRO_TEST_DATABASE_URL=…r32wib18 uv run pytest tests/migrations -q` → **168 passed (211.87s) pg18**; same against `r32wib17` → **168 passed (203.68s) pg17**. The Goal installed-base fixture reads the **real develop snapshot SHAs** (`c560d4c…`, `4675101…`, `66f3cea…`, `tests/migrations/test_goal_installed_base_upgrade.py:58-60`), builds each base by its own tree, and forward-upgrades with `alembic upgrade head` — **no stamp edit, no reset** (asserts stamp `056` → `063`, installed rows survive, durable composition readback). Fresh-install, single-head, downgrade/refusal and reapplication legs are inside the same 168. The branch's only edit to a shipped migration file remains the `043_invocation_quota_door.py` chain-history docstring — re-verified by diffing against `origin/develop`: no `revision`/`down_revision`/DDL line changes (prose only). `063_canonical_goals.py` declares `revision = "063"`, `down_revision = "062"`; full revision-graph scan: **one head (`063`), zero branch points**; `056_user_model_facts` → parent `043`, `057_run_store_planner_stability` → parent `056` — no merged identity reassigned.
- **Types:** `uv run mypy` over the seven shipped packages → **Success: no issues found in 899 source files**.

## Criterion → evidence map (no UNVERIFIED rows)

| Criterion | Executed evidence (this round) |
| --- | --- |
| 3-backend round-trip conformance | 70/70 pg18 + 70/70 pg17, `MAISTRO_REQUIRE_PG_LEGS=1`, fresh empty→063 DBs r32wg18/r32wg17, fail-loud proven with DSN unset |
| Append-only / stale-refused / one winner | conformance suite inside the 70/70, all backends, both majors |
| Subgoal lineage + recorded ownership change | conformance + model suites inside the 70/70 |
| Run binding immutable after admission | `test_run_goal_binding.py` inside the 70/70 + installed-base readback in 168/168 both majors |
| Cross-Workspace isolation; foreign ≡ missing | authorization suites inside the 70/70 |
| Production wiring (Hive + maistro-server) | source read (container.py:44/2414/2701/273/286, hive maistro_core.py:195, server main.py:344) + `test_goal_wiring.py` in the 70/70 |
| No second executor | convergence freeze exit 0 at CI's `--base 435dc1937e04` argv |
| Migration identity/ancestry preserved | revision-graph scan (one head, no branch points); 063 parented on 062; 056/057 meanings kept; 043 docstring-only re-verified by diff |
| Installed-base upgrades from real snapshots | c560d4c/4675101/66f3cea trees forward-upgraded, no stamp edit, both majors, inside 168/168 |
| Survival + durable restart readback | installed-base suite readback on both majors |
| Fresh-install / single-head / downgrade / reapplication | chain/single-head/downgrade/refusal/reapplication legs inside 168/168 |

## Closure-keyword review

Branch commit messages 435dc193..2208337b: **0** matches for `fixes|closes|resolves #NNN`. PR #1938 body (dispatch snapshot): "Draft auto-opened at work start (claim-stake; do not review yet). Refs #1572. …" — references only, no closure keywords.

## Disposition

No in-branch defect found; no code, tests, grants or ledgers changed; no test additions → no suite-inventory delta. All eleven acceptance criteria are proven first-hand at this head, on fresh round-32 databases, on both supported PostgreSQL majors. The merge-queue reds share exactly one root cause — the `GoalStatus` execution-lifecycles authorization — which by the deliberate two-merge rule (`scripts/ratchet_provenance.py:474-486`, AGENTS.md "A floor raise takes two merges") must land on `develop` first and cannot be created or authorized on this branch. Handoff unchanged from rounds 18–31: land the grant-only record into `develop` (append exactly one entry under `execution-lifecycles` in `quality/ratchet-authorizations.json`; owner, issue `#1572`, reason: GoalStatus is the Goal's desired-state DOMAIN lifecycle, never driven by a Run outcome; convergence freeze clean; candidate ledger banks it DOMAIN), sync `origin/develop` into `auto-1572`, re-queue. Lane databases `r32wg18`/`r32wg17` left migrated at `063` (plus `r32wib18`/`r32wib17` throwaways restored to head by the conftest); lane containers left up.
