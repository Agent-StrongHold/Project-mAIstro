# REPAIR-NOTES-1572 round 91 (dispatch head 654fe18a5a5f)

Job: /home/dev/maistro/jobs/8f9ed404d41b4f6fabe1b0a21b87e3fc — branch `auto-1572`,
head `654fe18a5a5fbd93819332a32b7114c37f35eb38`, base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Every claim below was (re-)executed first-hand this round; none inherited.

## 1. External state re-fetched — unchanged

- `git fetch origin develop` → tip `3c761d14db944a727fa0744444bc67cfe36d49f7`;
  `git merge-base HEAD origin/develop` = same SHA ⇒ merge-base == develop tip,
  nothing to merge, no develop-sync conflict exists.
- `git show origin/develop:quality/ratchet-authorizations.json | grep -c GoalStatus` → **0**
  (no GoalStatus grant anywhere on the base).
- Branch `quality/ratchet-authorizations.json` is **byte-identical to develop**
  (absent from `git diff --numstat origin/develop HEAD -- quality/`); the grant
  lives only in unmerged grant-only PR #1938.
- `git ls-remote` → `refs/heads/develop` unchanged `3c761d14db94`;
  `refs/pull/1938/head` unchanged `2f5dd46969fc` (open, unmerged; contained only
  by `origin/auto-1572`).
- Fetched `pull/1938/head` and read its diff against develop: **exactly one
  grant hunk** — `execution-lifecycles` grant `maistro.goals.model::GoalStatus`,
  owner `@BlakeMatthews-dev`, issue `#1572`, reason text identical in substance
  to the candidate ledger's DOMAIN rationale at
  `quality/execution-lifecycles.json` (Goal desired-state lifecycle, terminal
  states final, explicitly not a second execution identity).

## 2. The CI failure re-proven by execution at this head

- Exact CI argv (`quality.yml:1541`, no args):
  `uv run python scripts/check-execution-lifecycles.py` → **EXIT 1**, sole
  finding: `maestro`-none; verbatim
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 classified → 20
  discovered; baseline base `3c761d14db94`, candidate `654fe18a5a5f`).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed
  (test_the_shipped_ledger_matches_the_shipped_code), 28 passed**; captured
  stdout of the failing test is gate-identical (same baseline SHA, same sole
  finding) ⇒ is the merge-queue `test: failure` 1:1. The test
  (`tests/test_check_execution_lifecycles.py:367-374`) asserts
  `gate.main() == 0` against the real repository with the real base resolver,
  so it is red exactly while the base lacks the grant.

## 3. Two-merge mechanics re-read from source (not assumed)

- `scripts/ratchet_provenance.py:478-503` `load_authorizations` docstring,
  verbatim: *"a new grant does not take effect in the change that introduces it.
  Authorizing a floor-raise is now two merges -- the grant, then the regression
  it permits."* Grants are read from the **base revision**.
- `scripts/ratchet_provenance.py:258` `_refuse_self_reference` refuses a base
  that is the measured tree — a self-authorizing path does not exist.
- `scripts/check-execution-lifecycles.py:758-784`: trusted ledger and grants
  both resolved from `trusted_ref.base_sha`; `_unauthorized_additions`
  (`:705-710`) releases an added identity only if it is in the **base-side**
  grant map **or** its source was already visible at the base
  (`_discover_at_revision`). `maistro.goals/model.py` is new code, so the
  visible-at-base escape cannot apply. Candidate DOMAIN classification is
  present (`quality/execution-lifecycles.json` `lifecycles["maistro.goals.model::GoalStatus"]`)
  so classification is not the defect.
- Conclusion: **no branch-side repair exists** that is not prohibited
  weakening. In-branch grant = structural no-op (two-merge rule); merging
  develop = no-op (unchanged); removing/renaming the GoalStatus vocabulary =
  violates the issue mandate (lifecycle `ACTIVE → SATISFIED/CANCELLED/FAILED/
  SUPERSEDED`, terminal-final, explicitly "not a second execution identity",
  no GoalRun/OrchestratorRun). The repo policy in AGENTS.md states the same
  rule: "A floor raise takes two merges. Land the grant first, then the change."

## 4. Lane-brief CI-repair instructions executed — no amendment target

- Vulture at exact CI argv (`quality.yml:1079-1082`):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **EXIT 0**, 1323 reviewed
  → 1323 findings, `unclassified: 0`, `never_allowlist: 0` ⇒ nothing to fix and
  no reviewed-retained identity to amend into `quality/vulture-baseline.json`.
- Convergence freeze at exact CI argv (`formal-conformance.yml:70-77`):
  `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db944a727fa0744444bc67cfe36d49f7` → **EXIT 0**, "no unapproved new
  architecture island".

## 5. Issue acceptance re-executed first-hand at the dispatch head

Fresh container `goals_r91` (`pgvector/pgvector:pg18`, port 15491, removed after):

- Alembic empty → head: **EXIT 0**, single head `063`, final step
  `062 -> 063, The canonical Goal store: canonical_goals and its append-only
  children`; `pg_tables` shows exactly `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions`.
- Downgrade `063 -> 062` drops all three (count 0); re-upgrade restores 3.
- Goals suite `uv run pytest packages/maistro-core/tests/goals -q` with
  `MAISTRO_REQUIRE_PG_LEGS=1` + `MAISTRO_TEST_DATABASE_URL` +
  `MAISTRO_TEST_PG_DSN` (pg legs mandatory, skip impossible): **70 passed,
  0 failed, 0 skipped** — three-backend conformance round-trip, append-only +
  CAS one-winner + stale refusal, subgoal lineage with recorded agent
  transition, Run binding immutability, two-principal/two-Workspace isolation
  with foreign==missing, schema agreement, restart readback, Container wiring.
- Full migrations battery `uv run pytest tests/migrations -q` (same env):
  **168 passed** (229s), including the Goal installed-base upgrade tests.
- `grep -rn "GoalRun\|OrchestratorRun" packages/*/src/` → **0 hits** (no second
  executor), plus convergence-freeze EXIT 0 (criterion 7's named checker).
- Production composition source-read: `packages/maistro-core/src/maistro/container.py:44`
  (`from maistro.goals.wiring import wire_goal_store`), `:271-276` (authorized
  `goal_reader` seam), `:2412-2414` (`wire_goal_store(db_pool, pg_pool=...)`),
  `packages/maistro-core/src/maistro/goals/wiring.py:34-56` (durable
  `PgGoalStore` when a PG pool is configured).
- Driver deterministic checks in the job directory all green: sync resolved,
  `ruff check` "All checks passed!", `ruff format --check` 3288 files clean,
  9-file set 161 passed / 28 skipped, suite inventory ok (16334 identities).

## 6. Verdict

**BLOCKED — external, single-item, precisely scoped.** All seven issue
acceptance criteria plus the migration/installed-base boundary are proven by
execution at this head. The only red is the execution-lifecycles ratchet and
its shipped-ledger test, red solely because the GoalStatus grant is not
already-landed in the base — the repo's own two-merge rule. Unblock action
(requires maintainer authority, prohibited to this worker): merge grant-only
PR #1938 (head `2f5dd4696`, one grant hunk, no code) into `develop`; this
branch then syncs and the gate + test pass with **zero branch edits**
(executed simulations in rounds 74/77/81). No repair, weakening, gate change,
or ledger self-authorization is possible or attempted. Local-only, not a branch
defect: untracked gitignored `quality/ac-state.json` trips
`test_every_quality_json_state_surface_is_classified_once` in this worktree
only (`.gitignore:81`); untouched, CI passes it.

Docs-only round (this file). No code, test, or ledger changes; no inventory delta.
