---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# #1572 independent verification round 22 (2026-10-10)

Verifier+writer pass at the exact lane head `b2266fc2563c87a81696f42891a98aee4c58287c`,
develop base `435dc1937e0407ab4de198ffcced49860bb14ad2` (re-fetched this round,
unchanged). No code, tests, or ledger files edited; the gitignored
`quality/ac-state.json` worktree artifact was set aside once for one
classification test and restored sha256-identical (`fba4936e…` both sides).
Driver's 5 deterministic checks all returned 0 (ruff check/format, targeted
goals+migrations pytest 161p/28s, suite inventory 16334 = recorded).

## Acceptance re-executed first-hand at this head

- Fresh databases created this round on the lane servers — `auto1572_r22` on
  pg18 (:55712) and pg17 (:55717) — each migrated empty -> head through the
  real chain; the final step logged `062 -> 063, The canonical Goal store`.
- Goals suite at CI's env shape (`MAISTRO_REQUIRE_PG_LEGS=1`,
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL`): **70/70 passed,
  0 skipped on pg18 and 70/70 on pg17** (memory/sqlite/postgres conformance,
  append-only CAS, terminal-is-final per every terminal status, Subgoal
  lineage + recorded reassignment, foreign == missing on reads and mutations,
  Run binding immutable after admission, restart readback, Container wiring).
- Installed-base upgrades from the real develop snapshots
  (`tests/migrations/test_goal_installed_base_upgrade.py`) + migration chain
  (`tests/migrations/test_migration_chain.py`): **26/26 on pg18 and 26/26 on
  pg17** (8 installed-base each: byte-identical provenance for `056`/`057`,
  forward upgrade of c560d4c/4675101 trees with no reset or restamp, rows
  survive, durable Goal composition readback; 18 chain: single head 063,
  round-trip downgrade, refusals, reapplication).
- Meaningfulness spot-read: `test_a_foreign_goal_answers_exactly_like_a_missing_one`
  asserts identical type AND message for absent/foreign/blank principals on
  reads and mutations; `test_goal_revision_chain_is_append_only_with_one_cas_winner`
  races two appends from one pointer and asserts exactly one winner;
  `test_lifecycle_transitions_cas_and_terminal_is_final` walks every terminal
  status; `test_run_goal_binding.py` covers half-binding refusal and
  run-outcome-never-moves-goal-state.
- Production wiring read first-hand: `container.py:2414`
  (`goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)` passed to
  `create_container` at :2701); Hive composes via `create_container`
  (`packages/hive-conductor/backend/adapters/maistro_core.py:195`);
  maistro-server main.py:29 imports `create_container` from `maistro.container`.
- Convergence freeze: `scripts/check-m1-convergence-freeze.py --base 435dc193`
  exit 0 — no GoalRun / second executor / product-private Goal lifecycle.
- Quality pillars re-run: vulture at CI's exact args
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
  **1323 = 1323, exit 0** — no unbanked identity, so no
  `quality/vulture-baseline.json` amendment applies; check-model-egress
  (53 call sites, all dispositioned) and check-foreign-harness-egress exit 0;
  check-durable-table-inventory 112 tables exit 0.

## The three merge-queue reds at this head — one external cause, re-proven

1. **Quality gate:** `scripts/check-execution-lifecycles.py` exit 1, sole
   finding `maistro.goals.model::GoalStatus: NEW work-state vocabulary is
   absent from the trusted base and has no already-landed authorization`
   (19 classified -> 20 discovered). The gate loads authorizations from the
   merge base (`scripts/check-execution-lifecycles.py:773`,
   `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`, baseline
   printed as `base 435dc1937e04`); `quality/ratchet-authorizations.json` on
   the branch is byte-identical to origin/develop (`cmp` = identical) and
   develop's grant ledger carries zero GoalStatus entries — no
   self-authorization by construction (two-merge rule, AGENTS.md "a floor
   raise takes two merges"). The branch's only ledger edit is the +4-line
   GoalStatus DOMAIN classification in `quality/execution-lifecycles.json`.
2. **test job:** re-ran both candidate reds individually.
   `test_the_shipped_ledger_matches_the_shipped_code`
   (tests/test_check_execution_lifecycles.py:368) fails with the identical
   sole GoalStatus delta — the same external cause as red 1.
   `test_every_quality_json_state_surface_is_classified_once`
   (tests/test_branch_independence_repository.py:16) fails solely on
   `unclassified quality state: quality/ac-state.json` and passes with the
   gitignored (`.gitignore:81`, untracked) artifact set aside — CI checkouts
   cannot contain it, so CI sees exactly one red. Full-suite CI-shape runs at
   this content were executed in rounds 20/21 (2 failed 4976p / 1 failed
   4977p); not repeated this round — the two reds were isolated and re-proven
   directly instead.
3. **Coverage gate:** structural cascade read from
   `.github/workflows/quality.yml`: the `combine` step runs under
   `set -euo pipefail` and re-runs the root suite as the `--source=scripts`
   producer before `coverage xml`; the producer's non-zero exit on red 1
   aborts the step before any coverage artifact, reding the gate with no
   coverage regression.

## Unblock is upstream, not in-branch

origin/develop re-fetched this round: still `435dc1937e0407ab4de198ffcced49860bb14ad2`,
so there is no develop sync conflict and the branch is not behind. The
GoalStatus authorization must land on develop first (two-merge rule); the
gate then reads it from the new merge base. No in-branch action can turn the
execution-lifecycles gate green, and none remains to take: acceptance is
proven, the exact-debt-ledger is green at CI args, and no other pillar reds.
