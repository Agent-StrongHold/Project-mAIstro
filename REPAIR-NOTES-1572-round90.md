# #1572 round-90 repair verification (dispatch head ba11a0757ecb)

All crux claims below re-executed first-hand at HEAD `ba11a0757ecbadd72cfa03eafc9961ff6b771e23`
(clean tree; base `3c761d14db944a727fa0744444bc67cfe36d49f7`). Nothing assumed from rounds 74-89:
external state was re-fetched, the failing gates were re-run at their exact CI argv, and the full
PG acceptance battery was re-executed on a fresh container this round. The code tree at this HEAD
is byte-identical to the round-89 battery tree (`git diff --name-only 1f81c113d676 HEAD` filtered
of REPAIR-NOTES = 0 files), so prior acceptance evidence carries over to identical code — and was
re-run anyway.

## External state (re-fetched and re-proven this round)

- `git fetch origin` clean; `origin/develop` = `3c761d14db94` == merge-base of HEAD. develop has
  not moved since the round-89 check.
- `git grep -c GoalStatus origin/develop -- quality/` → **0 matches**: the base carries no
  execution-lifecycles grant for `maistro.goals.model::GoalStatus`.
- `git ls-remote origin refs/pull/1938/head` → `2f5dd46969fc...` unchanged: grant-only PR #1938 is
  still open/unmerged. develop lacking the grant is definitive, not inferred from the PR ref.
- `git diff origin/develop HEAD --stat -- quality/` → only `ac-state-notes/auto-1572.json`,
  `durable-table-retention.json`, `execution-lifecycles.json`; `ratchet-authorizations.json` is
  absent from the numstat: the branch carries **zero** grants (byte-identical to develop).

## The block, re-proven by execution at exact CI argv

- `uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541, no args) → **EXIT 1**,
  sole finding: `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19→20).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**; the sole
  failure's stdout is the same gate finding — the merge-queue `test: failure` is this 1:1.
- Two-merge mechanics re-read from source, not memory: `scripts/ratchet_provenance.py:478-503`
  docstring verbatim ("a new grant does not take effect in the change that introduces it … two
  merges — the grant, then the regression it permits"); `_refuse_self_reference` :257-270 refuses
  base=HEAD; gate `scripts/check-execution-lifecycles.py:773` reads `load_authorizations(RATCHET,
  base=trusted_ref.base_sha)`, `:783-784` `_unauthorized_additions(added, authorized,
  visible_at_base)`. An in-branch grant is a structural no-op **and** a self-approval.
- Candidate classification is present and correct: `quality/execution-lifecycles.json:89-92`
  carries the DOMAIN entry for `maistro.goals.model::GoalStatus` with the not-a-second-spine
  rationale. Classification is not the defect; the missing **already-landed authorization** is.
- Issue mandate re-read verbatim from the issue body (dispatch-context, issues/1572): "Goal
  lifecycle: e.g. active, satisfied, cancelled, failed, superseded. Transitions are
  compare-and-set on revision and state. Terminal states are final." and "No `GoalRun`,
  `OrchestratorRun`, second executor or product-private Goal lifecycle is introduced". So
  `GoalStatus` (`packages/maistro-core/src/maistro/goals/model.py:52-72`) is required: removing or
  renaming it to dodge the detector violates the acceptance criteria, and an unclassified
  lifecycle violates the freeze — both are prohibited weakening.
- Lane-brief vulture CI-repair exception re-run at exact argv (quality.yml:1079-1082):
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **EXIT 0**, 1323 reviewed = 1323 findings, unclassified 0,
  never_allowlist 0. **NO amendment target**: the one ledger this round is permitted to amend has
  nothing to amend, and it is not the ledger that is failing anyway.

## Gates that do pass (re-run at exact CI argv this round)

- `check-m1-convergence-freeze.py --base 3c761d14db94` (formal-conformance.yml:70-77) → **EXIT 0**
  ("no unapproved new architecture island").
- `check-convergence-matrix.py` (quality.yml:1377, no args) → **EXIT 0** (52 subsystems classify
  all 1401 production modules; 169 unreachable attributed).
- `grep -rn "GoalRun\|OrchestratorRun" packages/*/src` → rc=1, **0 occurrences** in production.
- Driver logs at this dispatch (check-0..4.log): `uv sync --locked --extra dev` ok, `ruff check .`
  "All checks passed!", `ruff format --check .` 3288 files, quick suite 161 passed / 28 skipped,
  suite inventory ok (16334 identities).

## Acceptance re-executed first-hand this round (fresh pgvector/pgvector:pg18 `goals_r90`, port 15490)

- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15490/goals_r90 uv run alembic upgrade
  head` from empty → **EXIT 0**, chain ends `062 -> 063, The canonical Goal store`; stamp 063;
  exactly `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` among the
  pg_tables (psql verified).
- Goals suite with `MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` and
  `MAISTRO_TEST_DATABASE_URL` all pointing at the migrated DB → **70 passed / 0 failed /
  0 skipped** (3-backend conformance, CAS one-winner, stale refusal, terminal-final, subgoal
  lineage, recorded agent transition, two-principals isolation, immutable run binding, schema
  agreement, restart readback, Container wiring — incl. test_goal_wiring.py, the shipped-Container
  proof the issue asks for).
- Full migration battery `uv run pytest tests/migrations -q` with `MAISTRO_TEST_DATABASE_URL` →
  **168 passed / 0 skipped / 0 failed** (200.7s): chain/single-head/unique-ID, installed-base
  forward upgrades without stamp edit, downgrade/refusal/reapplication.
- Production composition source-read: `container.py:44` imports `wire_goal_store`, `:276`
  `goal_reader` seam, `:2412-2414` wires it in `create_container`; `goals/wiring.py:34`.
- Known local-only failure re-confirmed and left untouched:
  `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_
  classified_once` fails in this worktree only via untracked **gitignored**
  `quality/ac-state.json` (`.gitignore:81`) picked up by the script's unconditional rglob; CI
  passed it. Not branch content; not repaired here (and wiping local files is prohibited).

## Verdict

**BLOCKED — unchanged**, on the same external prerequisite every round since 74: the
execution-lifecycles grant for `maistro.goals.model::GoalStatus` exists only in unmerged
grant-only PR #1938 (head 2f5dd46969fc, byte-verified via ls-remote this round). The two-merge
rule (source-verified above) makes in-branch self-authorization impossible, and the issue mandates
the vocabulary, so no in-branch repair exists that is not weakening. Once the maintainer merges
#1938 (or an equal grant-first PR) into develop and this branch syncs it, the gate and the
shipped-ledger test pass with zero branch edits — executed simulation: round-81 SIM1/SIM2 pair
(gate EXIT 0 "authorized: maistro.goals.model::GoalStatus … OK: 20 vocabularies", 29/29 tests)
re-derived from `resolve_baseline` reading the baseline at merge-base(base_sha, HEAD).

This round changed **this notes file only** (docs-only): no code, no tests, no ledger edits, no
inventory delta.
