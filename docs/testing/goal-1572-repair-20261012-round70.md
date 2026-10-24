# #1572 repair round 70 — verification record (2026-10-12, worktree `auto-1572` @ `3764123d9ab9`)

Dispatch head `3764123d9ab90cb84b116755ea199e22d595dc60`, develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Every claim below was re-executed
first-hand this round; none is inherited from rounds 37–69.

## 1. The merge-queue `test: failure`, re-derived

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  `quality.yml:1541`) → **exit 1**, provenance header
  `base 3c761d14db94 / candidate 3764123d9ab9, 19 classified lifecycles -> 20
  discovered lifecycles`, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization`.
- `tests/test_check_execution_lifecycles.py` → **1 failed / 28 passed**
  (`test_the_shipped_ledger_matches_the_shipped_code`, :368 runs the gate's
  `main()`), captured stdout identical to the gate run. This is the CI `test`
  job's sole failed step; the coverage `combine` failure inherits its dead
  producer and has no independent floor/diff-coverage deficit.

## 2. Why no in-branch repair exists (re-read from source, not assumed)

The sole defect is a missing **base-revision authorization**, not
classification: `quality/execution-lifecycles.json` already classifies
`maistro.goals.model::GoalStatus` as DOMAIN with a full rationale (never an
execution identity; Runs keep the canonical RunStatus). Eliminated paths:

1. **Base grant** — `origin/develop` re-fetched this round: tip
   `3c761d14db94` == merge-base (unchanged; no sync conflict exists). Its
   `quality/ratchet-authorizations.json` `execution-lifecycles` grants are
   exactly `services.rsi::RunStatus` + `maistro.graph.nodes.agent_delegate_remote::DelegationStatus`
   (both #1136); zero GoalStatus grants. All 385 issue comments through
   `2026-10-12T13:17:43Z` (dispatch re-captured 13:42) are bot progress
   markers; no maintainer grant. Landing it is a maintainer act
   (two-merge rule; #1833 precedent) — outside this worker's permissions.
2. **Base visibility** — `git show 3c761d14db94:packages/maistro-core/src/maistro/goals/model.py`
   fails (module is new in this branch), so `_discover_at_revision` can never
   admit GoalStatus as scanner expansion of pre-existing code.
3. **Candidate-ledger edit** — already classified (see above); the
   authorization check is independent of the candidate ledger.
4. **In-branch grant** — `load_authorizations` (`scripts/ratchet_provenance.py:478`)
   resolves the file at the **base revision**; docstring states the two-merge
   consequence verbatim. Also empirically moot: the in-branch
   `quality/ratchet-authorizations.json` is byte-identical to develop (`cmp`
   clean), i.e. no grant is present to double-count.
5. **Vocabulary removal/rename** — the issue scope names the lifecycle
   (`active, satisfied, cancelled, failed, superseded`); renaming members to
   slip under `_MIN_WORK_STATES=3` dodges the detector = prohibited gate
   weakening. Rejected.
6. **Lane-brief vulture exception** — no target:
   `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` (exact argv,
   `quality.yml:1079`) → **exit 0**, 1323 reviewed == 1323 findings,
   unclassified 0. Nothing to amend in `quality/vulture-baseline.json`.

## 3. Acceptance re-executed at this head (fresh pg18 `r70g18`, port 18722)

- Fresh install: empty DB → `alembic upgrade head` → single head `063`,
  final step `062 -> 063, The canonical Goal store: canonical_goals and its
  append-only children`.
- Goals suite `packages/maistro-core/tests/goals` with
  `MAISTRO_REQUIRE_PG_LEGS=1` and both DSNs
  (`MAISTRO_TEST_PG_DSN`, `MAISTRO_TEST_DATABASE_URL`): **70 passed / 0
  failed / 0 skipped** — three-backend round-trip conformance (memory,
  SQLite, PostgreSQL), append-only revisions with CAS single-winner, stale
  revision refusal, subgoal lineage with explicit recorded agent transition,
  two-principals Workspace isolation with foreign == missing, immutable Run
  `goal_id`/`goal_revision` binding, PG schema agreement, restart readback,
  shipped Container wiring (`goal_store` composed in production paths).
- Installed-base + migration chain
  (`tests/migrations/test_goal_installed_base_upgrade.py`,
  `tests/migrations/test_migration_chain.py`) with PG legs required:
  **26 passed** — forward upgrades of installed bases built from the actual
  develop snapshots `c560d4c` (user-model `056`) and `4675101` (planner
  `057`) without stamp edits, plus fresh-install single-head,
  downgrade/refusal, and reapplication coverage.
- AC7: `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db944a727fa0744444bc67cfe36d49f7`
  (exact CI argv, `formal-conformance.yml:77` shape) → **exit 0**, no
  unapproved new architecture island.
- `uv run mypy` over all seven package src trees → **Success: no issues found
  in 899 source files**.
- Driver checks at this head (`check-0..4.log`): uv sync resolved/checked,
  ruff check "All checks passed!", ruff format "3288 files already formatted",
  9-file test subset 161 passed / 28 skipped, suite inventory ok (16334
  identities match the recorded baseline). No inventory delta: no tests added
  or removed this round.

## 4. Verdict

**BLOCKED** — on the external maintainer `execution-lifecycles` grant for
`maistro.goals.model::GoalStatus` landing on `origin/develop` first
(two-merge rule, #1833/#1136 precedent). After it lands and this branch
merges develop, the gate and the shipped-ledger test pass with **zero
edits**; every other acceptance criterion is proven above at this head.

No code, test, or ledger changes this round; docs-only record, no inventory
delta.
