# Round 92 — repair verification at f870176603478af35d4102da85e4545c4cd32065 (HEAD)

Dispatch: job 67c41304e32a45b5bd0566413021a5d9, issue #1572, branch auto-1572,
develop base 3c761d14db944a727fa0744444bc67cfe36d49f7. Docs-only round: no
code, test, or ledger changes; no inventory delta (no tests added).

## External state re-fetched first-hand, none assumed

- `git fetch origin`: origin/develop tip `3c761d14db94` == merge-base ==
  base SHA — develop has NOT moved; no new commits, no grant landed.
- `git grep GoalStatus origin/develop -- quality/`: 0 hits (exit 1).
- `git ls-remote origin refs/pull/1938/head refs/heads/develop`: PR #1938 head
  UNCHANGED `2f5dd46969fc` (still open, still unmerged).
- Branch `quality/ratchet-authorizations.json`: absent from
  `git diff --numstat origin/develop -- quality/` — byte-identical to develop;
  the branch carries no grant (correct; an in-branch grant is structurally void,
  see below).

## Sole CI blocker re-proven by execution at HEAD

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) EXIT 1, sole finding: `maistro.goals.model::GoalStatus:
  NEW work-state vocabulary is absent from the trusted base and has no
  already-landed authorization` (19 -> 20).
- `uv run pytest tests/test_check_execution_lifecycles.py -q`: 1 failed
  (`test_the_shipped_ledger_matches_the_shipped_code`, asserts gate main()==0),
  28 passed — the merge-queue `test: failure` is this test, 1:1.
- Gate mechanics read from source: `scripts/check-execution-lifecycles.py:773`
  `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`,
  `:783-784` `_unauthorized_additions(added, authorized, visible_at_base)`;
  `scripts/ratchet_provenance.py:478-503` docstring verbatim: "a new grant
  does not take effect in the change that introduces it. Authorizing a
  floor-raise is now two merges"; `_refuse_self_reference` :257-270.
- Candidate-side DOMAIN classification IS present
  (`quality/execution-lifecycles.json:89-92`, rationale: desired-state
  lifecycle, never execution state) — classification is not the defect. The
  defect is the absent base-side grant, which lives only in unmerged PR #1938.
- No in-branch repair exists that is not weakening: the lifecycle
  (ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED, terminal-final) is mandated
  by the issue body; hiding or renaming it is the "product-private Goal
  lifecycle" the issue and the gate both prohibit.

## Lane-brief vulture CI-repair exception re-run: no amendment target

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv,
  quality.yml:1079-1082): EXIT 0, 1323 reviewed -> 1323 findings,
  unclassified 0, never_allowlist 0. The permitted amendment ledger
  (vulture-baseline.json) is green and is not the failing ledger.

## Other gates re-run at exact CI argv

- `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94`
  (formal-conformance.yml:70-77 shape): EXIT 0, "no unapproved new
  architecture island".
- `grep -rn "GoalRun\|OrchestratorRun" packages/*/src alembic`: 0 hits.
- Production wiring read at source: `container.py:44` imports
  `wire_goal_store`, `:273` `goal_store` field, `:276-286` `goal_reader`
  scoped seam, `goals/wiring.py:34-56` composes PG store via
  `ensure_goal_schema`.
- Driver logs (job dir check-*.log): sync, ruff check ("All checks passed!"),
  ruff format (3288 files), quick suite 161 passed/28 skipped, inventory ok
  (16334 identities).

## Acceptance re-executed first-hand on fresh pgvector/pgvector:pg18 (goals_r92, port 15492, container removed after)

- `DATABASE_URL=... uv run alembic upgrade head` on empty DB: EXIT 0, terminal
  step "062 -> 063, The canonical Goal store: `canonical_goals` and its
  append-only children"; exactly `canonical_goals`, `canonical_goal_revisions`,
  `canonical_goal_transitions` exist. Downgrade 063->062 drops 3 -> 0 tables;
  re-upgrade 062->063 clean (round-trip EXIT 0).
- Goals suite: `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_DATABASE_URL=...
  MAISTRO_TEST_PG_DSN=... uv run pytest packages/maistro-core/tests/goals -q`
  -> 70 passed, 0 failed, 0 skipped (three-backend conformance incl. PG leg;
  CAS one-winner, stale refusal, terminal-final, subgoal lineage + recorded
  agent transition, two-principals isolation foreign==missing, immutable run
  binding, schema agreement, restart readback, Container wiring).
- Full migrations battery: `uv run pytest tests/migrations -q` with both DSN
  vars -> 168 passed in 199.91s, including
  `test_goal_installed_base_upgrade.py` forward-upgrading real develop
  snapshots (c560d4c through user-model 056, 4675101 through planner 057)
  to the candidate head without stamp edits; single-head and
  downgrade/refusal coverage included.

## Local-only, not a branch defect

- `quality/ac-state.json` (607 KB, dated Oct 11) is untracked and gitignored
  (.gitignore:81) yet `scripts/check-branch-independence.py:206` rglobs
  `*.json` unconditionally, so
  `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
  fails in this worktree only. CI passed it (its sole failure was the ledger
  test). Untouched this round.

## Verdict

BLOCKED — unchanged, and the blocker is external by construction:

1. Merge grant-only PR #1938 (one `execution-lifecycles` grant for
   `maistro.goals.model::GoalStatus`) into develop — a maintainer action;
   I am prohibited from merging/pushing.
2. Sync this branch onto the new develop; gate and shipped-ledger test then
   pass with zero branch edits (two-merge mechanics: base-side grant
   authorizes the candidate's 19 -> 20).

Everything the branch itself can satisfy is satisfied and re-proven above.
