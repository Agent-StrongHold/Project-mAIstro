---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# #1572 independent verification round 21 (2026-10-10)

Read-only verifier pass at the exact lane head `6e60728b71378f8ea84f42b32e35b849b291a11c`,
develop base `435dc1937e0407ab4de198ffcced49860bb14ad2` (worktree entered
clean at that head; no code, tests, or ledger files edited; the gitignored
`quality/ac-state.json` worktree artifact was set aside once for one
classification test, then restored byte-identical — sha256 re-verified).

## Acceptance re-executed first-hand at this head

- Lane DBs `auto-1572-pg` (pg18, :55712) and `auto-1572-pg17` (pg17, :55717):
  fresh databases created, migrated empty -> 063 through the real chain
  (`062 -> 063, The canonical Goal store` is the final step).
- Goals suite at CI's env shape (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL`): **70/70 passed,
  0 skipped on pg18 and 70/70 on pg17** — memory/sqlite/postgres conformance
  round-trip, append-only revisions with stale-refusal and exactly-one CAS
  winner (appends and transitions), terminal-is-final across every terminal
  status, Subgoal lineage + recorded agent reassignment, cross-Workspace
  authorization with foreign == missing, Run binding immutable after
  admission, restart readback, Container wiring.
- Installed-base upgrades from the real develop snapshots
  (`tests/migrations/test_goal_installed_base_upgrade.py`): **8/8 on pg18 and
  8/8 on pg17**, zero skips — byte-identical provenance for `056`/`057`,
  forward upgrade of c560d4c (056) and 4675101 (057) and HITL-061 trees with
  no reset or restamp, rows survive, upgraded base serves the durable Goal
  composition; post-upgrade `alembic_version` = 063.
- Migration chain (`tests/migrations/test_migration_chain.py`): **18/18 on
  pg18** — single head, round-trip downgrade, refusals, reapplication.
- Convergence freeze: `scripts/check-m1-convergence-freeze.py --base
  435dc193` exit 0 — no GoalRun / second executor / product-private Goal
  lifecycle.
- Quality pillars re-run at CI args: mypy strict **899 files clean**;
  vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  **1323 = 1323, exit 0** (no ledger amendment applies); check-model-egress
  **20 = 20, exit 0**; check-foreign-harness-egress exit 0; fitness **23/23**.

## The three merge-queue reds re-proven at this head — one external cause

1. **Quality gate:** `scripts/check-execution-lifecycles.py` exit 1, sole
   finding `maistro.goals.model::GoalStatus: NEW work-state vocabulary is
   absent from the trusted base and has no already-landed authorization`
   (19 classified -> 20 discovered). The gate reads authorizations from the
   merge base (`scripts/check-execution-lifecycles.py:773`); base and branch
   `quality/ratchet-authorizations.json` are byte-identical and carry zero
   GoalStatus entries (grep = 0 in both), and the branch did not touch that
   file — no self-authorization by construction (two-merge rule).
2. **test job shape** (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest tests/
   --ignore=tests/tools/registry`): **2 failed 4976 passed, 135 skipped.**
   Red 1 = `test_the_shipped_ledger_matches_the_shipped_code` (the same
   external delta). Red 2 =
   `test_every_quality_json_state_surface_is_classified_once` — proven
   caused solely by the gitignored `quality/ac-state.json` worktree artifact:
   fails with it present, passes with it set aside (`.gitignore:81`;
   untracked, so a CI checkout cannot contain it). CI sees exactly one red.
3. **Coverage gate:** structural cascade — quality.yml runs the root suite
   as the `--source=scripts` producer under `set -euo pipefail` before
   `coverage xml`; the producer exits non-zero on red 1, so no coverage
   artifact is produced and the combine step errors
   ("producer contributed no coverage data").

## Unblock is upstream, not in-branch

No open PR carries the grant: #1855's file list (dispatch snapshot) touches
no `quality/ratchet-authorizations.json`. Landing the supplied GoalStatus
authorization on develop, then syncing this branch, is the only path; the
branch itself has no remaining in-scope defect.

## Closure hygiene

No `fixes/closes/resolves #N` in any commit message on
`435dc193..6e60728b`; PR #1938 body says "Refs #1572" only. No issue-closure
actions taken.
