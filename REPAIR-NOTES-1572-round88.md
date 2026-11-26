# #1572 round-88 repair verification (dispatch head 8d28403d0666)

All crux claims below were re-executed first-hand at HEAD `8d28403d06660aea27b309c486c468e050475bbf`
(clean tree; base `3c761d14db944a727fa0744444bc67cfe36d49f7`). Nothing assumed from rounds 74-87.
The code tree at this HEAD is byte-identical to the round-87 dispatch head `d32089303` for all
code paths (`git diff --stat d32089303 HEAD` = the round-87 notes file only), so round-87's
full PG acceptance battery applies to this exact code.

## External state (re-fetched and re-proven this round)

- `git fetch origin` clean; `origin/develop` = `3c761d14db94` == merge-base of HEAD. develop has not moved.
- `git grep -c GoalStatus origin/develop -- quality/` → **0 matches**: the base carries no
  execution-lifecycles grant for `maistro.goals.model::GoalStatus`.
- `git diff --numstat origin/develop HEAD -- quality/` → `ratchet-authorizations.json` absent from
  the numstat (byte-identical): this branch carries **zero** GoalStatus grants. The grant lives only
  in open, unmerged PR #1938 (head `2f5dd46969fc` per rounds 85-87 ls-remote).

## The block, re-proven by execution at exact CI argv

- `uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541, no args) → **EXIT 1**,
  sole finding: `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
  trusted base and has no already-landed authorization` (19 → 20 lifecycles).
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**; the failed
  test's captured stdout is gate-identical (same sole finding, same base/candidate) = the
  merge-queue `test: failure` explained 1:1. No second defect hides behind it.
- Two-merge mechanics re-read from source: `scripts/ratchet_provenance.py:478-503` —
  `load_authorizations` reads `quality/ratchet-authorizations.json` **from the base revision**;
  docstring verbatim: "a new grant does not take effect in the change that introduces it.
  Authorizing a floor-raise is now two merges". Gate calls it at
  `scripts/check-execution-lifecycles.py:773` (`base=trusted_ref.base_sha`) and filters via
  `_unauthorized_additions` (:784). `_refuse_self_reference` (`ratchet_provenance.py:258`) refuses
  pointing the base at HEAD.
- Candidate classification is not the defect: `quality/execution-lifecycles.json:89` classifies
  `maistro.goals.model::GoalStatus` as DOMAIN in the candidate ledger.
- No in-branch repair exists: (a) an in-branch grant is a structural no-op (grants are read from the
  base) and would be self-approval besides; (b) removing/renaming GoalStatus violates the issue
  text, which mandates the lifecycle ("Goal lifecycle: e.g. active, satisfied, cancelled, failed,
  superseded... Transitions are compare-and-set... Terminal states are final") implemented at
  `packages/maistro-core/src/maistro/goals/model.py:52-72`; (c) dodging the detector or weakening
  the gate is prohibited.
- Lane-brief vulture CI-repair exception re-run at exact argv (quality.yml:1079-1082:
  `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → **EXIT 0**, 1323 = 1323,
  unclassified 0, never_allowlist 0: the permitted `quality/vulture-baseline.json` amendment has
  **no target** this round.

## Acceptance re-execution at this HEAD

- Goals suite `uv run pytest packages/maistro-core/tests/goals -q` → **48 passed, 22 skipped**
  (PG legs skip without a DB), identical to prior rounds. Round-87 ran the same code tree with
  `MAISTRO_REQUIRE_PG_LEGS=1` on a fresh isolated pgvector/pg18: **70 passed / 0 failed / 0 skipped**
  (3-backend conformance, CAS one-winner, stale refusal, terminal-final, subgoal lineage +
  recorded agent transition, two-principals isolation, immutable run binding, schema agreement,
  restart readback, Container wiring) plus alembic empty→head EXIT 0 with single head 063
  ("062 -> 063, The canonical Goal store") and exactly canonical_goals / canonical_goal_revisions /
  canonical_goal_transitions. Evidence carries to this HEAD by byte-identical code tree.
- Convergence freeze `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94`
  (formal-conformance.yml:70-77 argv) → **EXIT 0**, "no unapproved new architecture island".
  `GoalRun`/`OrchestratorRun` absent from production `packages/**.py` (grep emitted no lines).
- Driver logs green (job dir): uv sync OK, `ruff check` "All checks passed!", `ruff format --check`
  3288 files clean, root suite 161 passed / 28 skipped, suite inventory 16334 OK.

## Known local-only artifact (unchanged, not a branch defect)

`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
fails only in this worktree via untracked, gitignored `quality/ac-state.json` (.gitignore:81) found
by the checker's unconditional rglob; CI passes it (its 1 failure was the shipped-ledger test only).
Left untouched.

## Verdict

**BLOCKED** — unchanged, and the block is external: `origin/develop` must gain the
execution-lifecycles authorization for `maistro.goals.model::GoalStatus` (merge grant-only PR
#1938, or an equal grant-first PR). Once the grant is landed on develop, the gate and the
shipped-ledger test pass with **zero branch edits** (proven by round-81/87 executed simulations:
grant-only base → gate EXIT 0 "authorized: maistro.goals.model::GoalStatus", 20 vocabularies, and
29/29 ledger tests). No action available inside this worktree resolves it without prohibited
GitHub mutations or gate weakening.

Docs-only round: this notes file; no code, test, or ledger changes; no inventory delta.
