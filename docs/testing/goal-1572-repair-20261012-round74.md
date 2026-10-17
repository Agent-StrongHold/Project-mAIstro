# #1572 repair round 74 — first-hand re-verification at e9c384a3 (dispatch head)

Round 74 re-derived the block and the acceptance state first-hand at dispatch head
`e9c384a36419c1d5bbb480fab3be8fd8508ea7da` (worktree clean, tree code-identical to the
round-73 battery; the only delta since `a383c3984` is round-73's docs note). Nothing was
assumed from prior rounds' claims. **New this round: the "grant lands ⇒ gate passes"
handoff claim is no longer inferred from mechanism reading — it was executed and
demonstrated (see B6).**

## Blocker re-derived first-hand (unchanged, external)

- B1. `git fetch origin` re-run: origin/develop tip == merge-base ==
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (**UNCHANGED**, 0 behind — no develop sync
  conflict, nothing to merge); `git grep GoalStatus origin/develop -- quality/` →
  no matches (0 grants on develop).
- B2. `uv run python scripts/check-execution-lifecycles.py` — the exact CI argv
  (`.github/workflows/quality.yml:1541`, no args) — **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
  base and has no already-landed authorization` (19 -> 20 lifecycles).
- B3. This is the merge-queue `test: failure` 1:1: re-run
  `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**;
  the failed test `test_the_shipped_ledger_matches_the_shipped_code` (line 368) prints
  the gate's stdout verbatim (same sole finding). No other test in the file fails.
- B4. Two-merge rule re-read in source this round: `scripts/ratchet_provenance.py`
  `load_authorizations` (docstring verbatim: "a new grant does not take effect in the
  change that introduces it … two merges"); `resolve_baseline` precedence
  explicit > `RATCHET_BASE_REV` > GitHub event base > `origin/develop`, and the resolved
  base is reduced to `merge-base(base, HEAD)`. The candidate ledger already classifies
  GoalStatus DOMAIN (`quality/execution-lifecycles.json:89`) and the gate still fails —
  self-classification is non-authorizing via `_unauthorized_additions`
  (`scripts/check-execution-lifecycles.py:705/783-784/806-807`). The branch's
  `quality/ratchet-authorizations.json` is byte-identical to origin/develop
  (`git diff origin/develop HEAD -- quality/ratchet-authorizations.json` = empty), so an
  in-branch grant re-add is a proven no-op.
- B5. **Grant content verified from the open grant PR:** `git fetch origin
  pull/1938/head` (`2f5dd46969fc`); its `quality/ratchet-authorizations.json` delta vs
  origin/develop is exactly one new `execution-lifecycles` entry
  (`maistro.goals.model::GoalStatus`, owner `@BlakeMatthews-dev`, issue `#1572`,
  rationale matching the branch's own ledger row).
- B6. **DECISIVE — the handoff was executed, not just argued.** Plumbing simulation,
  zero refs touched (isolated `GIT_INDEX_FILE`, `commit-tree`; throwaway detached
  worktree, removed afterwards):
  - `SIM 89bb7871055f` = origin/develop tree + #1938's grant file (single-file delta);
  - `SIM2 e4ffd99034a1` = this branch's tree, parented on SIM (the conflict-free merge
    of the PR into a grant-carrying develop — what a merge queue tests);
  - `RATCHET_BASE_REV=$SIM … check-execution-lifecycles.py` in SIM2 → **exit 0**:
    `authorized: maistro.goals.model::GoalStatus: #1572 -- @BlakeMatthews-dev: …`
    `OK: 20 work-state vocabularies, all classified (3 CANONICAL, 8 CONVERGE, 7 DOMAIN,
    2 PROJECTION)`.
  So once the grant lands on develop (merge #1938's grant, or any equivalent maintainer
  grant) and the branch is synced/merged, the gate passes with **zero branch edits**.
  (First attempt with the base not in the candidate's ancestry still failed — confirming
  the merge-base reduction is exactly why an in-branch grant can never work.)
- B7. No in-branch resolution exists: (a) in-branch grant → no-op (B4); (b) removing or
  renaming GoalStatus violates the issue-mandated lifecycle
  (active/satisfied/cancelled/failed/superseded) and merely dodges the detector —
  prohibited weakening; (c) `RATCHET_BASE_REV=HEAD` is self-reference, refused and
  conceptually the self-authorization the mechanism exists to close; (d) origin/develop
  has nothing to merge (B1).
- B8. Lane-brief vulture CI-repair exception has **no target**: exact CI argv
  (`quality.yml:1079`) `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323 == 1323. The
  failing gate is execution-lifecycles, not the vulture ledger; the prohibition on
  ordinary ledger/grant edits stands.

## Acceptance re-executed first-hand this round (fresh pg18 DB `r74g18`)

- A1 (3-backend conformance round-trip), A2 (append-only revisions, stale update
  refused, concurrent CAS one winner), A3 (subgoal lineage preserves parent/Project;
  owning-agent change is an explicit recorded transition), A4 (Run admission binds
  goal_id/goal_revision, immutable afterwards), A5 (two principals, two Workspaces;
  foreign Goal ≡ missing), A6 (production composition wires the store; Container test) —
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=$DSN MAISTRO_TEST_DATABASE_URL=$DSN
  uv run pytest packages/maistro-core/tests/goals -q` → **70 passed / 0 failed /
  0 skipped** (includes PG schema agreement, restart readback, and wiring legs).
- A7 (no GoalRun/second executor/product-private lifecycle) — `uv run python
  scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67cfe36d49f7`
  (exact PR-policy argv, `.github/workflows/formal-conformance.yml:77`) → **exit 0**.
- A8 (merged 056/057 identities preserved; Goal migration appended with centrally
  coordinated unused identity) — `DATABASE_URL=$DSN uv run alembic upgrade head` on the
  empty fresh DB → single head `063 (head)`, final step `062 -> 063, The canonical Goal
  store`, stamp `063`, and all three tables present (`canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions`).
- A9/A10 (populated installed-base upgrades from the real pre-Goal develop snapshots
  `c560d4c`→056 and `4675101`→057; data survival; readback) —
  `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py -q` → **8 passed**.
- A11 (fresh-install, single-head/unique-ID, supported downgrade/refusal, reapplication)
  — `uv run pytest tests/migrations/test_migration_chain.py -q` → **18 passed**
  (26 passed total for the two files, 0 skipped once the PG DSN is exported).
- Static hygiene: `uv run mypy <7 package src dirs>` → **Success: no issues found in 899
  source files**. Driver logs at this exact head: `uv sync --locked --extra dev` ok,
  `ruff check .` ok, `ruff format --check .` (3288 files) ok, suite 161 passed / 28
  skipped, suite inventory ok (16334 identities). Driver logs are in the job directory
  (`check-0.log` … `check-4.log`).

## Verdict

**BLOCKED** — solely on the external maintainer execution-lifecycles grant for
`maistro.goals.model::GoalStatus` (two-merge rule; grant-only PR #1938 head
`2f5dd46969fc` is exactly the required shape and is open). Round 74's new contribution:
B6 demonstrates by execution that after the grant lands on develop, this branch's gate
and the shipped-ledger test pass with zero branch edits. No code, test, or ledger
changes were made this round (docs-only commit; no inventory delta).
