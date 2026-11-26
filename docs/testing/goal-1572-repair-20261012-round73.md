# #1572 repair round 73 — first-hand re-verification at a383c3984 (dispatch head)

Round 73 re-derived the block and the acceptance state first-hand at dispatch head
`a383c39847255ae09f65342203a847589c398d8d` (worktree clean, tree byte-identical to the
round-72 verification battery). Nothing was assumed from prior rounds' claims; every leg
below was executed this round unless marked carried.

## Blocker re-derived first-hand (unchanged, external)

- `uv run python scripts/check-execution-lifecycles.py` — the exact CI argv
  (`.github/workflows/quality.yml:1541`, no args) — **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
  base and has no already-landed authorization` (19 -> 20 lifecycles). This is the
  merge-queue `test: failure`: the root-suite test
  `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  re-run this round = **1 failed / 28 passed**, stdout identical to the gate.
- Two-merge rule re-read in source: `scripts/ratchet_provenance.py:478-495`
  `load_authorizations` reads grants **from the base revision**; its docstring states
  verbatim "a new grant does not take effect in the change that introduces it.
  Authorizing a floor-raise is now two merges". The candidate ledger already classifies
  GoalStatus as DOMAIN (`quality/execution-lifecycles.json:89-92`) and the gate still
  fails — self-classification is non-authorizing by `_unauthorized_additions`
  (`scripts/check-execution-lifecycles.py:705`, message at :807).
- In-branch `quality/ratchet-authorizations.json` is byte-identical to origin/develop
  (`git diff origin/develop HEAD -- quality/ratchet-authorizations.json` = 0 lines), so
  re-adding a grant in-branch is a proven no-op (also empirically shown by prior round 59
  at 2f5dd4696).
- `git fetch origin` re-run: origin/develop tip == merge-base == `3c761d14db94`
  (**UNCHANGED** — no develop sync conflict, nothing to merge);
  `git grep GoalStatus origin/develop -- quality/` -> no matches (0 grants on develop).
- Captured GitHub state (dispatch context, 2026-10-12T15:45Z): 395 issue comments contain
  zero `GoalStatus` mentions; PR #1938 is open with `mergeable_state: blocked`, its 11
  inline comments and 1 review are `chatgpt-codex-connector[bot]` only (newest
  2026-10-04). No maintainer execution-lifecycles grant for `GoalStatus` exists anywhere.
- Lane-brief vulture CI-repair exception has **no target**: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (exact CI argv, quality.yml:1079) -> **exit 0**, 1323 reviewed
  identities == 1323 findings, nothing unbanked. The failing gate is execution-lifecycles,
  not the vulture ledger; the prohibition on ordinary ledger/grant edits stands.

No legitimate in-branch repair exists: an in-branch grant is a no-op (base-revision read),
dropping the ledger row fails the audit in the other direction, and renaming/splitting the
vocabulary would dodge the `_MIN_WORK_STATES=3` detector or violate the issue-mandated
lifecycle (active/satisfied/cancelled/failed/superseded) — a prohibited gate weakening.

## Acceptance re-executed first-hand this round

- Driver deterministic checks (this job's check-0..4.log at this exact head): uv sync,
  `ruff check .`, `ruff format --check .` (3288 files), 9-file pytest set **161 passed /
  28 skipped**, suite inventory ok (**16334** collected == recorded).
- Goals suite with durable legs required on a freshly created pg18 database `r73g18`
  (pgvector/pgvector:pg18, healthy):
  `DATABASE_URL=... uv run alembic upgrade head` migrated empty -> **063**, single head,
  final step "062 -> 063, The canonical Goal store: `canonical_goals` and its append-only
  children"; `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest packages/maistro-core/tests/goals -q` -> **70 passed / 0 failed /
  0 skipped** (3-backend conformance memory/sqlite/postgres, append-only CAS one winner,
  stale-revision refusal, subgoal lineage, explicit recorded agent transition,
  two-principals isolation with foreign==missing, immutable run binding, schema agreement,
  restart readback, Container wiring). Note: pointing the legs at the shared `maistro`
  database or at an empty database errors in fixture setup
  (`UndefinedTableError: relation "canonical_projects" does not exist`) — the legs require
  a *migrated* database, per the skip message at
  `packages/maistro-core/tests/goals/test_run_goal_binding.py:65`; on a fresh migrated DB
  everything is green (the shared-DB error is an operator artifact, not a branch defect).
- Post-migration schema asserted via psql on r73g18: `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` all present;
  `alembic_version` = `063`; spine tables (`canonical_runs`/`canonical_node_runs`/
  `canonical_attempts`) coexist — substrate alongside the one execution spine.
- AC7: `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94` (CI argv
  shape, formal-conformance.yml:77) -> **exit 0**, no unapproved new architecture island.
- Carried from the round-72 battery at this byte-identical tree (documented in the
  round-72 note and commit a383c3984): installed-base forward upgrades from the actual
  pre-Goal develop snapshots c560d4c (056) and 4675101 (057) without stamp edits,
  downgrade 063 -> 062 -> 063, mypy 899 files clean, both production compositions
  (Hive + maistro-server) re-read in source.

## Verdict

**BLOCKED** — unchanged, and now re-proven this round. The sole failing CI signal is the
execution-lifecycles gate via the shipped-ledger test, and it can only be cleared by a
maintainer landing an execution-lifecycles authorization for
`maistro.goals.model::GoalStatus` on origin/develop first (two-merge rule; precedent:
#1136 landed RunStatus+DelegationStatus grants, #1833 landed vulture identity grants).
After that grant lands, this branch merges develop and the gate and the shipped-ledger
test pass with zero branch edits.

Docs-only round note; no code, test, or ledger changes; no inventory delta.
