# REPAIR-NOTES-1572 round 97 (2026-10-13)

Dispatch: issue #1572, head `7aec3ca581e428b7e9805d7ef3543bc92ac31915` (round-96 notes
commit, unchanged), base `3c761d14db944a727fa0744444bc67cfe36d49f7`. Driver logs at this
head: sync 256/214, ruff check "All checks passed!", format 3288 files, pytest 161p/28s,
inventory 16334 ok (job 86d841df check-0..4.log). Dispatch brief: "Previous block
(resolve it as part of this round): worker requested attention: BLOCKED".

## Resolution attempt: external state re-fetched first-hand (read-only)

- `git fetch origin` → `origin/develop` tip `3c761d14db94` == merge-base == base. **No new
  commits landed on develop.**
- `git grep -c GoalStatus origin/develop -- quality/` → rc=1, **0 grants on develop**.
- `git ls-remote origin refs/pull/1938/head` → `2f5dd46969fc` **unchanged**;
  `git fetch origin refs/pull/1938/head` + `git merge-base --is-ancestor FETCH_HEAD
  origin/develop` → **NOT merged**. The only GoalStatus execution-lifecycles grant still
  lives in open, unmerged PR #1938.

So the one resolution path this lane is allowed to take (sync the already-landed grant
from develop) does not exist yet. Everything below re-proves the block and re-executes
acceptance on this exact tree; nothing was assumed from round <= 96 records.

## Block re-proven by execution at this head

- Code-tree identity: `git diff --stat 1f81c113d..HEAD` = 8 REPAIR-NOTES docs files, 913
  insertions, **zero non-notes files** (exclusion filter over notes names verified empty).
  The code tree is byte-identical to the tree rounds 89–96 battery-ran.
- Gate at exact CI argv (`quality.yml:1541`, no args):
  `uv run python scripts/check-execution-lifecycles.py` → **EXIT 1**, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
  base and has no already-landed authorization`, `19 classified -> 20 discovered`,
  `baseline: base 3c761d14db94`, `candidate: 7aec3ca581e4`.
- Merge-queue `test: failure` reproduced 1:1:
  `tests/test_check_execution_lifecycles.py` → **1 failed / 28 passed**, failing test
  `test_the_shipped_ledger_matches_the_shipped_code`, its FAIL output byte-identical in
  substance to the direct gate run's sole finding.
- Branch `quality/` numstat vs develop: `ac-state-notes/auto-1572.json`,
  `durable-table-retention.json`, `execution-lifecycles.json` (+4) only — **no
  ratchet-authorizations.json row in the branch at all**; and even an in-branch grant is a
  structural no-op (below).

## Two-merge mechanics re-read from source (not from notes)

- `scripts/check-execution-lifecycles.py:773`: `authorized =
  prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` — grants are read from the
  **base revision**; `_unauthorized_additions(added, authorized, visible_at_base)`
  (:783-784) admits only base-side grants or `_discover_at_revision(base_sha)` aliases,
  which new code can never satisfy; `_refuse_self_reference`
  (scripts/ratchet_provenance.py:257-270) bars HEAD-as-base.
- `scripts/ratchet_provenance.py:482-505` docstring verbatim: "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now two merges --
  the grant, then the regression it permits".
- Classification is **not** the defect: the branch ledger already banks the candidate as
  DOMAIN at `quality/execution-lifecycles.json:88-92` (verified via
  `git diff origin/develop...HEAD -- quality/execution-lifecycles.json`). Sole missing
  piece = base-side authorization.

## No permitted in-branch repair target (re-run, not inherited)

- Removing/renaming/hiding `GoalStatus` would violate the issue body verbatim
  (dispatch-context.json `repos/Agent-StrongHold/Project-mAIstro/issues/1572`, 8156
  chars): "**Goal lifecycle:** e.g. active, satisfied, cancelled, failed, superseded.
  Transitions are compare-and-set on revision and state. Terminal states are final." —
  prohibited weakening.
- Lane-brief vulture CI-repair exception re-run at exact argv (`quality.yml:1079-1082`):
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **EXIT 0**, 1323 = 1323, unclassified 0, never_allowlist
  0. **No amendment target exists**; the permitted ledger surface is already clean.
- `GoalRun`/`OrchestratorRun`: `grep -rn packages/*/src` → rc=1, 0 hits (exit taken
  without a pipe this round; round-96's identical claim re-verified correctly).

## Acceptance re-executed first-hand on fresh pgvector/pg18 `goals_r97` (port 15497, container removed after)

- `DATABASE_URL` (not MAISTRO_TEST_PG_DSN — `maistro/config/database.py:148` requires it
  for alembic, per #187) → `uv run alembic upgrade head` **EXIT 0**, ends
  `062 -> 063, The canonical Goal store`, single head; information_schema shows **exactly**
  `canonical_goals`, `canonical_goal_revisions`, `canonical_goal_transitions` among 75
  public tables.
- `uv run alembic downgrade 062` **EXIT 0** → 0 canonical_goal% tables;
  re-`upgrade head` **EXIT 0** → 063 restored (round-trip clean).
- Goals suite `uv run pytest packages/maistro-core/tests/goals -q` with
  `MAISTRO_REQUIRE_PG_LEGS=1` + `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL`
  (var names verified in test sources first: conformance :136-143, wiring :183-208,
  schema-agreement :38/:67): **70 passed / 0 failed / 0 skipped** — no skips, PG legs
  enforced (CAS one-winner, terminal-final, subgoal lineage, two-principals isolation,
  immutable run binding, schema agreement, wiring).
- Convergence freeze at exact CI argv (`formal-conformance.yml:73-77`):
  `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94...` →
  **EXIT 0**, "no unapproved new architecture island".

## Verdict

**BLOCKED — unchanged, external dependency.** The merge-queue `test: failure` is the
shipped-ledger test asserting the execution-lifecycles gate, which fails on exactly one
finding: the issue-mandated `maistro.goals.model::GoalStatus` (19→20) has no
already-landed authorization because the two-merge design reads grants from the base
revision, and the grant exists only in open PR #1938 (head `2f5dd46969fc`, verified
unmerged into develop `3c761d14db94` by ls-remote + ancestry check this round). No
in-branch repair exists that does not weaken the issue-mandated lifecycle; the permitted
CI-repair surfaces (vulture ledger amendment) verified empty by execution. Unblocking
action for the maintainer: **merge grant-only PR #1938 into develop**, then this branch
syncs and passes the gate + test with zero branch edits (executed simulations in rounds
74/77/81/87). Docs-only delta this round (this notes file); no code/test/ledger changes;
no inventory delta.
