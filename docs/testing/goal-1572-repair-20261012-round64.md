# #1572 repair round 64 — 2026-10-12 (job e018a2adaa3b4da682baab5f5b77c80f)

Dispatch head `5bbb970db3354f0cb0269c9c037caf5ab746f333` (round-63 docs commit; `git diff
db091060d..HEAD` is six docs/testing round-record files only, so the code is identical to
the state rounds 58–62 battered). Base `3c761d14db944a727fa0744444bc67cfe36d49f7` (==
merge-base, re-fetched this round — origin/develop has NOT moved; no GoalStatus grant has
landed). Every claim below was executed first-hand this round; no prior claim trusted.

## Sole blocker, re-proven at this exact head

`uv run python scripts/check-execution-lifecycles.py` (exact CI argv, quality.yml:1541)
exits 1: `19 classified lifecycles -> 20 discovered lifecycles`, sole finding
`maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted base
and has no already-landed authorization`.
`tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
fails on the same finding (1 failed / 28 passed) — this is the merge-queue `test: failure`;
the coverage `combine` step inherits the dead producer.

## No in-branch repair exists (re-derived from source this round)

- `scripts/ratchet_provenance.py` `load_authorizations` (:478) reads grants from the base
  revision; docstring verbatim: "a new grant does not take effect in the change that
  introduces it. Authorizing a floor-raise is now two merges". `resolve_baseline`
  precedence explicit arg > `RATCHET_BASE_REV` > event base > `origin/develop`, with
  `_refuse_self_reference` blocking base==HEAD (self-authorization = gate weakening).
- `scripts/check-execution-lifecycles.py` `_unauthorized_additions` (:705) passes only via
  a base grant or base source visibility; `_discover_at_revision` (:674) needs
  `git show {base}:.../maistro/goals/model.py`, impossible — `git grep GoalStatus
  origin/develop` exits 1 (module new in this branch).
- origin/develop's `execution-lifecycles` grants are exactly
  `services.rsi::RunStatus` + `maistro.graph.nodes.agent_delegate_remote::DelegationStatus`
  (both #1136 pre-existing-vocabulary precedent); zero GoalStatus.
- The branch's candidate ledger classifies GoalStatus as DOMAIN with rationale, but
  `_unauthorized_additions` exists precisely so a candidate classification cannot
  authorize a new identity. Renaming/removing the vocabulary violates the issue-mandated
  lifecycle ("e.g. active, satisfied, cancelled, failed, superseded") or dodges the
  detector — both prohibited.
- Lane-brief vulture amendment exception has NO target:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (exact CI argv, quality.yml:1079) exits 0,
  1323 reviewed == 1323 findings, unclassified 0.
- `quality/ratchet-authorizations.json` is byte-identical to origin/develop (`cmp`
  clean) — the round-60 restoration holds; no trailing-newline drift remains.

## Acceptance evidence re-executed first-hand this round (all green except the blocker)

- ruff `check .` + `format --check .`: clean (3288 files). mypy on the seven package src
  trees: "Success: no issues found in 899 source files".
- Convergence freeze at CI argv: `uv run python scripts/check-m1-convergence-freeze.py
  --base 3c761d14db944a727fa0744444bc67cfe36d49f7` -> exit 0, "no unapproved new
  architecture island" (no GoalRun/OrchestratorRun/second executor).
- pg18 (pgvector:pg18, `auto-1572-pg` :55712) fresh DB `r64g18`: `alembic upgrade head`
  empty->063, single head `063 (head)`, final step "062 -> 063, The canonical Goal store".
  pg17 (`auto-1572-pg17` :55717) fresh DB `r64g17`: same chain to 063.
- Goals suite with durable legs required
  (`MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` + `MAISTRO_REQUIRE_PG_LEGS=1`):
  **70 passed, 0 skipped** on pg18 AND on pg17 — three-backend conformance
  (memory/sqlite/postgres), append-only + CAS single-winner + stale refusal, Subgoal
  lineage, foreign==missing via ScopedGoalStore, immutable run binding, container wiring
  (`test_goal_wiring.py`), restart readback, schema agreement. First attempt with only
  `MAISTRO_TEST_PG_DSN` set errored 6 schema-agreement setups
  (`MAISTRO_TEST_DATABASE_URL` empty) — fixture requires both env names, not a branch
  defect; green once both set.
- events + runs suites with the same env on pg18: **1888 passed, 3 skipped** (run binding
  admission/immutability against the durable spine).
- Downgrade leg on r64g18: 3 `canonical_goal*` tables -> `alembic downgrade 062` -> 0
  tables -> `upgrade head` -> 3 tables.
- Migration identity: `git diff origin/develop..HEAD -- alembic/versions/056_*.py
  alembic/versions/057_*.py` is empty (merged user-model 056 and planner 057 preserved
  byte-identically); `063_canonical_goals.py` has `revision = "063"`,
  `down_revision = "062"` (appended after the integrated develop head, single head).
  Installed-base upgrade fixtures (c560d4c->056, 4675101->057 forward to 063) were
  executed first-hand in rounds 60/62 at this identical code (docs-only delta verified
  above); not re-run this round.
- Driver check logs (job dir): uv sync resolved, ruff clean, format clean, targeted
  9-file set 161 passed / 28 skipped, suite inventory ok (16334 identities).

## Local-only, not a branch defect

`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_
classified_once` fails only in this worktree via untracked, gitignored scratch
`quality/ac-state.json` (left untouched, as rounds 59–63 did). CI passes it.

## Verdict: BLOCKED on the external two-merge grant

The only failing acceptance item is the execution-lifecycles ratchet, which by design
cannot be satisfied inside the branch that introduces the vocabulary: a maintainer must
land an `execution-lifecycles` grant for `maistro.goals.model::GoalStatus` on develop
(same treatment PR #1833 gave this branch's vulture identities), then this branch merges
develop and the gate + shipped-ledger test pass with zero further edits. No code, test, or
ledger change is made this round; no inventory delta (no tests added).
