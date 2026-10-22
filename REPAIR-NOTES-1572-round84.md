# Round 84 — independent re-verification at acfc942bd (dispatch head)

Every leg below was executed first-hand this round in `/home/dev/Git/wt/auto-1572`
(HEAD `acfc942bdf71365662fd5c5bd647c841d29541f9`, tree clean, exactly the dispatch
head). Nothing was assumed from round ≤ 83 claims.

## 1. Repo state

- `git fetch origin` re-run: **origin/develop UNCHANGED** at `3c761d14db94`;
  tip == merge-base of HEAD (nothing to sync, no conflict to resolve).
- `git grep GoalStatus origin/develop -- quality/` → **exit 1 (0 matches)**:
  no GoalStatus execution-lifecycles grant has landed on develop.
- `git ls-remote origin refs/pull/1938/head` → still `2f5dd46969fc…`
  (the grant-only commit); PR #1938 **not merged**.
- `git diff --numstat origin/develop HEAD -- quality/` → only
  `ac-state-notes/auto-1572.json` (+17), `durable-table-retention.json` (+39),
  `execution-lifecycles.json` (+4). **`ratchet-authorizations.json` absent from the
  diff → byte-identical to develop** (in-branch grant removed in 8510776ae/826cd0879;
  an in-branch grant is a structural no-op anyway per §2).

## 2. The block — re-proven at CI's exact argv

- CI argv confirmed: `quality.yml:1541`
  `uv run python scripts/check-execution-lifecycles.py`.
- Executed at HEAD: **EXIT 1**, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 → 20 vocabularies;
  baseline `base 3c761d14db94`, candidate `acfc942bdf71`).
- Merge-queue `test: failure` reproduced 1:1:
  `uv run pytest tests/test_check_execution_lifecycles.py -q` →
  **1 failed / 28 passed**, sole failure
  `test_the_shipped_ledger_matches_the_shipped_code` (asserts `gate.main() == 0`),
  captured stdout byte-identical to the gate run above.
- Two-merge mechanics re-read from source:
  - `scripts/ratchet_provenance.py:478-510` `load_authorizations` — docstring verbatim:
    "a new grant does not take effect in the change that introduces it.
    Authorizing a floor-raise is now two merges -- the grant, then the regression
    it permits". Grants are read **from the base revision**.
  - `scripts/check-execution-lifecycles.py:758/:773`: baseline resolved to the
    trusted base (`3c761d14db94`), grants loaded via
    `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`.
  - `_refuse_self_reference` (`scripts/ratchet_provenance.py:257-270`) refuses
    `RATCHET_BASE_REV=HEAD` self-authorization.
- Candidate ledger already classifies the vocabulary as DOMAIN
  (`quality/execution-lifecycles.json:89`) → classification is not the defect;
  the defect is solely the missing **already-landed** authorization.
- No legitimate in-branch repair exists: renaming/removing `GoalStatus` violates the
  issue-mandated lifecycle (active/satisfied/cancelled/failed/superseded, terminal-final
  CAS) or dodges the detector (prohibited weakening); an in-branch grant is a
  proven no-op (read from base; empirically failed at 2f5dd4696 in round 59);
  self-referential base is refused.
- **Repair = land the grant hunk on develop (merge grant-only PR #1938), then this
  branch passes gate + test with zero branch edits** (simulation-proven rounds
  74/77/81: gate EXIT 0 under `RATCHET_BASE_REV=<develop+grant>`).

## 3. Lane-brief vulture CI-repair exception — no amendment target

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` (exact CI argv, quality.yml:1079-1082) → **EXIT 0**,
`1323 reviewed identities -> 1323 findings`, `unclassified: 0`, `never_allowlist: 0`.
The permitted `quality/vulture-baseline.json` amendment has nothing to amend.

## 4. Acceptance criteria re-executed first-hand (fresh pg18 this round)

Fresh `pgvector/pgvector:pg18` container `goals_r84` (PG 18.6, port 15484, new DB
`goals_r84`):

- `DATABASE_URL=… uv run alembic upgrade head` → **EXIT 0**, chain ends
  `062 -> 063, The canonical Goal store`; `alembic heads` → `063 (head)` (single head);
  `pg_tables` shows exactly `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions`.
- Goals suite with all three backends live:
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…
  uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed /
  0 skipped** (includes `test_run_goal_binding.py` against the migrated DB:
  3-backend conformance round-trip, append-only CAS one winner, stale refusal,
  terminal-final, subgoal lineage, explicit recorded agent transition,
  two-principals isolation foreign==missing, immutable run binding,
  Container wiring).
- Full migration battery: `uv run pytest tests/migrations -q` →
  **168 passed / 0 skipped / 0 failed** (chain + single-head + unique revision IDs,
  installed-base forward upgrades, downgrade/refusal/reapplication).
- AC7 convergence freeze at CI argv (`formal-conformance.yml:71-77`,
  `--base $BASE_SHA` = `3c761d14db94`):
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94`
  → **EXIT 0** ("no unapproved new architecture island").
- No competing execution identity: `grep -rn "GoalRun\|OrchestratorRun" packages/*/src`
  → **exit 1 (absent)**.
- Production composition re-read in source:
  `packages/maistro-core/src/maistro/container.py:44` imports `wire_goal_store`,
  `:273` `goal_store` field, `:276-286` `goal_reader` → `ScopedGoalStore` seam
  (#1572), `:2414` `wire_goal_store(...)` called in `create_container`;
  `packages/maistro-core/src/maistro/goals/wiring.py:34` defines it.
- mypy (AGENTS.md file set): **Success: no issues found in 899 source files**.
- `uv run ruff check .` → All checks passed!; `uv run ruff format --check .` →
  3288 files already formatted.
- Driver logs at this exact head: sync ok (check-0), ruff ok (check-1),
  format ok (check-2), focused set 161 passed / 28 skipped (check-3),
  suite inventory ok 16334 identities (check-4).
- Known local-only artifact (not a branch defect, untouched): untracked
  gitignored scratch `quality/ac-state.json` (`.gitignore:81`) makes
  `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
  fail in this worktree only; CI passed it.

## 5. Verdict

**BLOCKED** — the sole red CI signal (lifecycle gate + its shipped-ledger test;
coverage `combine` inherits the dead producer) is the external two-merge
authorization for `maistro.goals.model::GoalStatus`. Every branch-testable
acceptance criterion is green first-hand this round. Once the grant-only PR #1938
lands on develop and this branch syncs, gate + test pass with **zero branch edits**.

No code, test, or ledger changes this round (docs-only: this notes file) →
no inventory delta.
