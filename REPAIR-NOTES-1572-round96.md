# REPAIR NOTES — issue #1572, round 96 (job 5727dcda1fd24fea9cf42404d94bc988)

Dispatch head `3b5efa3a0ba68ba8f760a50f2c95e7a4762367cf` (clean worktree, matches
the assigned starting head exactly). Driver logs in the job directory are green:
uv sync resolved/checked 256/214 packages (check-0.log), `ruff check` "All checks
passed!" (check-1.log), `ruff format --check` 3288 files (check-2.log), subset
pytest **161 passed / 28 skipped** (check-3.log), suite inventory **ok (16334
unique identities)** (check-4.log). The dispatch again repeats the standing
block ("worker requested attention: BLOCKED") and offers the vulture-ledger
CI-repair exception. This round re-proved the block by execution, re-derived
the gate mechanics from source (not from prior notes), and re-executed the
acceptance battery first-hand on a fresh PG container. Nothing below is
carried over on trust.

## 1. External state re-fetched first-hand (2026-10-13, this round)

- `git fetch origin` → `git rev-parse origin/develop` =
  **3c761d14db944a727fa0744444bc67cfe36d49f7** and
  `git merge-base HEAD origin/develop` = the same SHA: **develop is unchanged**
  and is still exactly the merge base of this branch. No new commits to sync.
- `git grep GoalStatus origin/develop -- quality/` → **no matches (0 grants)**:
  develop carries no execution-lifecycles authorization for
  `maistro.goals.model::GoalStatus`.
- `git ls-remote origin refs/pull/1938/head` →
  **2f5dd46969fc38b23502d5e40ef35d1f0879ba14, unchanged**: the grant-only PR
  #1938 is still open/unmerged. Had it merged, develop would have advanced
  past 3c761d14db94; it has not.
- `git diff --numstat origin/develop..HEAD -- quality/` → exactly
  `quality/ac-state-notes/auto-1572.json` (17+), `quality/durable-table-retention.json`
  (39+), `quality/execution-lifecycles.json` (4+ = the GoalStatus DOMAIN row at
  lines 89–92). **No `ratchet-authorizations.json` row on this branch** — the
  grant lives only in PR #1938; an in-branch grant is a structural no-op (§2).

## 2. Gate mechanics re-derived from source (this round, not from prior notes)

- Exact CI argv (`.github/workflows/quality.yml:1541`):
  `uv run python scripts/check-execution-lifecycles.py` → **EXIT 1**, sole
  finding: `maistro.goals.model::GoalStatus: NEW work-state vocabulary is
  absent from the trusted base and has no already-landed authorization`
  (19 classified → 20 discovered).
- `scripts/check-execution-lifecycles.py:758,773`: the trusted baseline and
  `load_authorizations(RATCHET, base=trusted_ref.base_sha)` are both read from
  the **base revision** (merge-base with the event base; here 3c761d14db94).
- `scripts/check-execution-lifecycles.py:705-709` `_unauthorized_additions`:
  a discovered addition passes only if it is in the **base-side** grants or in
  `_discover_at_revision(trusted_ref.base_sha, …)` (names already visible at
  base, :783). `GoalStatus` is new, so neither path can admit it from this
  branch.
- `scripts/ratchet_provenance.py:478-520` `load_authorizations` docstring,
  verbatim: *"a new grant does not take effect in the change that introduces
  it. Authorizing a floor-raise is now two merges."*
- `scripts/ratchet_provenance.py:257-270` `_refuse_self_reference`: a base
  resolving to HEAD is refused; `:272-296` `_base_rev`: precedence is explicit
  argument → `RATCHET_BASE_REV` → GitHub event base → `origin/develop`. CI
  always names the PR base. **There is no in-branch state that can authorize
  this branch's own new vocabulary.**
- The shipped-ledger test reproduces the gate 1:1:
  `uv run pytest tests/test_check_execution_lifecycles.py -q` →
  **1 failed / 28 passed**, the failure being
  `test_the_shipped_ledger_matches_the_shipped_code` with output
  byte-identical to the direct gate run. This is the merge-queue
  `test: failure` 1:1.

## 3. No in-branch repair exists that is not prohibited weakening

- **In-branch grant** → structural no-op (§2; grants are read from base).
- **Remove/rename/hide `GoalStatus`** → violates the issue mandate, re-read
  verbatim from the dispatch issue body: *"Goal lifecycle: e.g. active,
  satisfied, cancelled, failed, superseded. Transitions are compare-and-set
  on revision and state. Terminal states are final. A Run's outcome never
  sets Goal state implicitly."* and *"No GoalRun, OrchestratorRun, second
  executor or product-private Goal lifecycle is introduced"*. Gutting the
  mandated lifecycle would also orphan the 70 passing goals tests (§4).
- **Re-classify in `quality/execution-lifecycles.json`** → the candidate
  DOMAIN classification is already present (:89–92, rationale naming #1572);
  classification is not the defect — the missing *base-side authorization* is.
- **`visible_at_base` / base-rev manipulation / detector dodging** → refused
  by `_refuse_self_reference`/CI event base, or prohibited weakening.
- **Lane-brief vulture exception** re-run at exact CI argv
  (quality.yml:1079-1082: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) →
  **EXIT 0, 1323 reviewed identities → 1323 findings, unclassified 0,
  never_allowlist 0**: no amendment target exists; nothing is genuinely dead.
- **Workflow diffs are additive-only** (`git diff origin/develop..HEAD --
  .github/workflows/`): ci.yml adds a "Goal stores conform across memory,
  SQLite and PostgreSQL" step (mirror of the Workspace step, with
  MAISTRO_REQUIRE_PG_LEGS=1); quality.yml appends
  `packages/maistro-core/tests/goals` to an existing path list. No gate is
  removed, weakened, or re-argued. No other gate/script/ratchet files touched.

## 4. Acceptance re-executed first-hand on this exact tree

Code-tree identity: `git diff --name-only ba11a0757..HEAD` (round-89 full
battery tree) → **6 files, all `REPAIR-NOTES-1572-round9*.md` at repo root,
684 insertions, zero non-notes files** — the production tree is byte-identical
to the tree of prior full batteries, and this round re-executed the core
battery anyway on a fresh container (`goals_r96`, pgvector/pgvector:pg18,
port 15496, removed after):

- `DATABASE_URL=postgresql://maistro:maistro@localhost:15496/maistro
  uv run alembic upgrade head` → **EXIT 0**, final line
  `Running upgrade 062 -> 063, The canonical Goal store: canonical_goals and
  its append-only children`; catalogue then contains exactly
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions`
  among 75 public tables.
- `alembic downgrade 062` → **EXIT 0** (3 → 0 canonical_goal% tables);
  re-upgrade → **EXIT 0** (0 → 3). Reversible both ways.
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…
  uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0
  failed / 0 skipped** (variable names verified in test sources first:
  test_goal_store_conformance.py:138, test_goal_wiring.py:183/208,
  test_goal_pg_schema_agreement.py:38).
- Convergence freeze at exact CI argv
  (`uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7`, formal-conformance.yml:70-77) →
  **EXIT 0**: "no unapproved new architecture island".
- `grep -rn "GoalRun|OrchestratorRun"` across all `packages/*/src` →
  **exit 1 (absent)** — no second executor identity.
- `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .`
  → 3288 files already formatted (this round, this head).

## 5. Verdict

**BLOCKED — unchanged, and the block is external and structural.** The only
merge-queue failure (`test: failure` = shipped-ledger test = execution-lifecycles
gate) cannot be resolved on this branch by any non-weakening edit: the
execution-lifecycles ratchet reads authorizations from the merge base, the
base has zero GoalStatus grants, and the grant lives in unmerged PR #1938.
Resolution: a maintainer merges grant-only PR #1938 (exactly one
execution-lifecycles authorization for `maistro.goals.model::GoalStatus`,
owner BlakeMatthews-dev, issue #1572) into develop; this branch then syncs
(fast-forward — develop is the merge base) and the gate and the shipped-ledger
test pass with **zero branch edits**, per the mechanism re-derived from source
in §2. No docs-only note changes affect any gate; no inventory delta (no test
files touched; suite inventory ok 16334 in driver logs).
