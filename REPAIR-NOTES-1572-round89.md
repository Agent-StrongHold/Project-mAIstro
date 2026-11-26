# #1572 round-89 repair verification (dispatch head 1f81c113d676)

All crux claims below re-executed first-hand at HEAD `1f81c113d6769b00c6187d030ee495feb53bc6f4`
(clean tree; base `3c761d14db944a727fa0744444bc67cfe36d49f7`). Nothing assumed from rounds 74-88:
round-88's claims were independently re-derived, not trusted. The code tree at this HEAD is
byte-identical to the round-87 PG-battery tree (`git diff --stat d32089303 HEAD` = notes files
only), and this round additionally re-ran the full PG acceptance battery on a fresh container.

## External state (re-fetched and re-proven this round)

- `git fetch origin` clean; `origin/develop` = `3c761d14db94` == merge-base of HEAD. develop has
  not moved since the round-88 check.
- `git grep GoalStatus origin/develop -- quality/` → **0 matches** (rc=1): the base carries no
  execution-lifecycles grant for `maistro.goals.model::GoalStatus`.
- `git ls-remote origin refs/pull/1938/head` → `2f5dd46969fc...` unchanged: grant-only PR #1938 is
  still open/unmerged. develop lacking the grant is definitive, not inferred from the PR ref.
- `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` → 0 lines: branch carries
  **zero** grants; the file is byte-identical to develop.

## The block, re-proven by execution at exact CI argv

- `uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541, no args) → **EXIT 1**,
  sole finding: `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19→20).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**; the sole
  failure's stdout is the same gate finding — the merge-queue `test: failure` is this 1:1.
- Two-merge mechanics re-read from source, not memory: `scripts/ratchet_provenance.py:478-503`
  docstring verbatim ("a new grant does not take effect in the change that introduces it … two
  merges — the grant, then the regression it permits"); gate
  `scripts/check-execution-lifecycles.py:773` reads `load_authorizations(RATCHET,
  base=trusted_ref.base_sha)`, `:783-784` `_unauthorized_additions(added, authorized,
  visible_at_base)`. An in-branch grant is a structural no-op **and** a self-approval.
- Candidate classification is present and correct: `quality/execution-lifecycles.json:89` carries
  the DOMAIN entry for `maistro.goals.model::GoalStatus` with the not-a-second-spine rationale.
  Classification is not the defect; the missing **already-landed authorization** is.
- `packages/maistro-core/src/maistro/goals/model.py:52-72`: `GoalStatus` is the issue-mandated
  lifecycle (ACTIVE while pursued; SATISFIed/CANCELLED/FAILED/SUPERSEDED terminal and final, with
  `TERMINAL_GOAL_STATUSES` / `_ALLOWED_TRANSITIONS`). Removing or renaming it to dodge the
  detector would violate the acceptance criteria and weaken the gate — prohibited.

## Lane-brief vulture CI-repair exception: no amendment target

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (exact argv, quality.yml:1079-1082) → **EXIT 0**: `1323 reviewed identities →
  1323 findings`, `unclassified: 0`, `never_allowlist: 0`. The one ledger this round is permitted
  to amend has nothing to amend; the failing gate is execution-lifecycles, not vulture.

## Acceptance re-executed first-hand this round (fresh pgvector:pg18 container `goals_r89`, port 15489)

- `DATABASE_URL=…15489/maistro uv run alembic upgrade head` on the **empty** DB → **EXIT 0**,
  chain ends `062 -> 063, The canonical Goal store: canonical_goals and its append-only
  children`; single version row `063`; exactly `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions` exist among the 75 public tables.
- `MAISTRO_REQUIRE_PG_LEGS=1` with both DSN vars (`MAISTRO_TEST_PG_DSN` for the conformance/store
  legs per conftest:136/:385, `MAISTRO_TEST_DATABASE_URL` for the schema-agreement legs per
  test_goal_pg_schema_agreement.py:38/:56) → `uv run pytest packages/maistro-core/tests/goals -q`
  → **70 passed / 0 failed / 0 skipped**: 3-backend conformance, CAS one-winner, stale refusal,
  terminal-final, subgoal lineage, recorded agent transition, two-principals isolation
  (foreign==missing), immutable run binding, migration-063 vs ensure-schema agreement, restart
  readback, Container wiring.
- `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67cfe36d49f7`
  (exact CI argv, formal-conformance.yml:70-77 `args=(--base "$BASE_SHA")`) → **EXIT 0**: "no
  unapproved new architecture island".
- `grep -rn "GoalRun\|OrchestratorRun" packages/*/src --include='*.py'` (third_party excluded) →
  **0 lines**: no second execution spine in production code.
- Driver logs at this exact head (job aabc5464 check-0..4): `uv sync --locked --extra dev` OK,
  `ruff check .` "All checks passed!", `ruff format --check .` 3288 files clean, root suite
  161 passed / 28 skipped, `check-suite-inventory.py --suite packages/maistro-core/tests` OK
  (16334 identities).
- Local-only, not a branch defect: `quality/ac-state.json` is untracked and gitignored
  (`.gitignore`), which is why `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` fails only in this worktree; the file
  was left untouched and CI passed that test.

## Verdict

**BLOCKED** — unchanged, and no in-branch repair exists:

1. The authorization for `maistro.goals.model::GoalStatus` must sit in
   `quality/ratchet-authorizations.json` **at the merge base** `3c761d14db94` (structural, from
   `ratchet_provenance.py` source, quoted above). develop carries zero GoalStatus grants.
2. The grant exists only in open, unmerged PR #1938 (head `2f5dd46969fc`). Landing it requires
   merging that PR to develop — a GitHub mutation this worker is prohibited from performing.
3. In-branch alternatives are all prohibited or structurally void: an in-branch grant is a no-op
   plus self-approval; removing/renaming GoalStatus violates the issue-mandated lifecycle
   (model.py:52-72); weakening the detector is gate weakening. Executed simulations (rounds 81/87)
   proved the gate prints `authorized: maistro.goals.model::GoalStatus` and the ledger tests run
   29/29 with zero branch edits once the grant lands on develop.

**Resolution path (external, zero branch edits):** merge grant-only PR #1938 (or an equal
grant-first PR) to develop; the branch then syncs the base and the execution-lifecycles gate and
shipped-ledger test pass as-is.

Docs-only change (this notes file). No code, test, or ledger changes; no inventory delta.
