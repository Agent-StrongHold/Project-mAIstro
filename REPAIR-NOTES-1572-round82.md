# Repair notes — #1572 round 82 (job 2a97f5fe62cb40909ebce5aab7581803)

Dispatch head `36f0f9c9a519c7a313b083c1b28d27e2c3224d9e`, develop base `3c761d14db94`.
Round verdict: **BLOCKED on the external execution-lifecycles grant** — unchanged conclusion;
every claim re-proven first-hand this round at the dispatch head, none assumed.

## 1. External state re-check (fresh this round)

- `git fetch origin develop`: tip **unchanged** — `origin/develop` = `3c761d14db94` =
  merge-base = `git ls-remote refs/heads/develop` (branch 183 ahead; no sync conflict exists).
- `git grep GoalStatus origin/develop -- quality/` → **0 matches**: develop carries no
  GoalStatus ledger entry and no grant.
- `git ls-remote refs/pull/1938/head` → still `2f5dd46969fc` (open, unmerged).
- **Precision on the in-branch grant**: commit `2f5dd4696` (PR #1938's hunk, +6/−1 on
  `quality/ratchet-authorizations.json`) is an ancestor of this branch, but it was
  **removed again in-branch** by `8510776ae` ("Remove incorrect GoalStatus authorization …
  should be landed on develop first per two-merge rule") plus `826cd0879` (structure
  restore after the removal initially broke the JSON nesting).
  `git diff origin/develop HEAD -- quality/ratchet-authorizations.json` is now **empty** —
  the branch carries no grant at all; the grant exists only in unmerged PR #1938.

## 2. Blocking gate at HEAD, exact CI argv

`uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541, no args):

```
ratchet: execution-lifecycles  [python ast, metric v3]
  baseline: base 3c761d14db94
  candidate: 36f0f9c9a519
  19 classified lifecycles  ->  20 discovered lifecycles
FAIL
  - maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
    base and has no already-landed authorization
EXIT=1
```

`uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**
(`test_the_shipped_ledger_matches_the_shipped_code`, captured stdout gate-identical) — the
merge-queue `test: failure` is this, 1:1. Sole failure.

## 3. Why no in-branch repair exists (re-derived from source this round)

- The issue mandates the lifecycle itself ("Goal lifecycle: active, satisfied, cancelled,
  failed, superseded … terminal states are final"). Any implementation is a new work-state
  identity; renaming/removing `GoalStatus` would dodge the detector or delete mandated
  behavior — both prohibited.
- Grants are read from the **merge base** — `ratchet_provenance.load_authorizations`
  docstring verbatim this round (ratchet_provenance.py:492-495): "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now two merges —
  the grant, then the regression it permits." The branch cannot carry the authorization for
  its own vocabulary, and `_refuse_self_reference` (:258) refuses `RATCHET_BASE_REV=HEAD`.
- **Lane-brief vulture CI-repair exception — no target**: exact quality.yml argv
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → **EXIT 0**,
  `1323 reviewed identities -> 1323 findings`, `unclassified: 0`, `never_allowlist: 0`.
  The permitted `quality/vulture-baseline.json` amendment has nothing to amend; the sole
  failing identity is an execution-lifecycle vocabulary, not a vulture row.
- Round-74/77/81 plumbing simulation (grant re-parented onto develop → gate EXIT 0,
  shipped-ledger test 29/29, control run EXIT 1) carries over: once the grant lands on
  develop, this branch passes with **zero branch edits**.

## 4. Issue acceptance re-executed at HEAD (first-hand this round)

- Goals conformance suite, sqlite+memory legs: `pytest packages/maistro-core/tests/goals -q`
  → **48 passed / 22 skipped** (skips = PG legs without a DSN).
- **Fresh pg18 run this round**: created scratch DB `goals_r82` in the running
  `maistro-postgres` (pgvector/pgvector:pg18) container; `alembic upgrade head` from empty →
  **single head 063**, final step `062 -> 063, The canonical Goal store`; catalogue shows
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` stamped 063.
- Goals suite with PG legs **required**:
  `MAISTRO_REQUIRE_PG_LEGS=1 pytest packages/maistro-core/tests/goals -q` →
  **70 passed / 0 failed / 0 skipped** (3-backend conformance round-trip, append-only
  revisions with one CAS winner, stale refusal, terminal-final, subgoal lineage + recorded
  agent transition, two-principals isolation foreign==missing, immutable run binding,
  PG/SQLite schema agreement, restart readback, Container wiring). Scratch DB dropped after.
- SQLite/Alembic schema parity: 1 passed / 1 skipped.
- Convergence freeze at CI argv (formal-conformance.yml:73-78):
  `check-m1-convergence-freeze.py --base 3c761d14db94` → **EXIT 0**, "no unapproved new
  architecture island"; `GoalRun|OrchestratorRun` grep over maistro-core/server/hive
  sources → **0 occurrences**.
- Production composition, source-read: `goals/wiring.py:34` defines `wire_goal_store`;
  `maistro/container.py:44` imports it, **:2414 calls it inside `create_container`**,
  :271-276 derives the authorized `goal_reader` seam; shipped compositions call
  `create_container` — `maistro_server/main.py:344` and
  `hive-conductor/backend/adapters/maistro_core.py:148/:195`.
- Driver logs at this head (job dir check-*.log): sync ok, ruff check "All checks passed",
  3288 files formatted, 161 passed / 28 skipped, suite inventory 16334 ok.
- Known **local-only** artifact (not a branch defect), re-confirmed: untracked gitignored
  `quality/ac-state.json` (gitignored via .gitignore:81, 0 tracked copies) trips
  `test_every_quality_json_state_surface_is_classified_once` via unconditional rglob in
  check-branch-independence.py:206; CI passes it. Left untouched.

## 5. External action required to unblock (maintainer)

Land the **grant-only** hunk on develop — the `quality/ratchet-authorizations.json`
`execution-lifecycles` entry for `maistro.goals.model::GoalStatus` (owner
`@BlakeMatthews-dev`, issue #1572) currently held by open PR #1938 (`2f5dd4696`). After it
lands: gate EXIT 0 and shipped-ledger test 29/29 with zero branch edits (proven by the
round-74/77/81 re-parenting simulation; merge-base becomes the grant-carrying develop tip,
no rebase required). Per campaign rules this worker performs no GitHub mutations, so the
merge is the maintainer's action.

No code, test, ledger, or gate changes were made this round; this file is the only edit.
No inventory delta (no tests added or removed).
