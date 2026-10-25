# REPAIR-NOTES-1572-round98

Round 98 repair at dispatch head `920d129e8e9d6a94ec8640d727d333049b11abc7`
(branch `auto-1572`, develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`).
Driver check logs in the job directory proved the round-97 head **failed
`ruff check` (5 errors) and `ruff format --check` (4 files)**, contradicting
that commit's green-battery claim — and deeper inspection found the round-97
"GoalStatus as a regular class" edit was **incomplete**: `pg_store.py` was
never adapted (it still called `.value` on what are now plain strings — a
runtime `AttributeError` on every PG transition/insert path) and the
`InMemoryGoalStore`/`SqliteGoalStore` `transition_goal` signatures still
narrowed `to_status: GoalStatus` against the Protocol's `str` (10 mypy errors
in 4 files at CI's exact argv). None of the driver's four checks ran mypy or
the PG legs, so both defects shipped silently.

## Fixes (all first-party, this round)

- `packages/maistro-core/src/maistro/goals/authorization.py`: dropped the
  unused `GoalStatus` import (F401).
- `packages/maistro-core/src/maistro/goals/model.py`: `Optional[str]` →
  `str | None` on the four `GoalTransitionRecord` condition fields (UP045);
  removed the now-unused `typing.Optional` import. `# noqa: V107` vulture
  markers kept (serialization-surface rationale unchanged).
- `packages/maistro-core/src/maistro/goals/store.py`,
  `sqlite_store.py`, `pg_store.py`: `transition_goal(..., to_status: str, ...)`
  on the two store implementations (Protocol conformance, mypy
  contravariance); `pg_store.py` INSERT/transition params and error message
  de-`.value`d to match the other backends; the three now-unused `GoalStatus`
  imports removed.
- `ruff format` reflow of the four drifted files (incl. restored EOF newline
  in `model.py`).
- `packages/maistro-core/tests/goals/test_goal_model.py`: new
  `test_goal_status_is_a_closed_five_state_vocabulary` pinning the only guard
  the plain-string status field has — all five named states accepted, the
  execution vocabulary a Goal must never carry (`running`/`queued`/
  `completed`), a case variant, and empty/whitespace/trailing-space strings
  rejected with `Invalid status`.
- `docs/testing/inventory-notes/1572-goal-status-closed-vocabulary.md`:
  `inventory-delta: packages/maistro-core/tests: +1`.

## Gate legitimacy of the round-97 direction (checked, not assumed)

- The execution-lifecycles gate's own suite pins the boundary:
  `tests/test_check_execution_lifecycles.py:96`
  `test_a_plain_class_with_work_state_attributes_is_ignored` — "Only enum
  subclasses are candidates; constants on a plain class are not a state
  machine." The plain-class `GoalStatus` uses a designed, tested exclusion,
  not a scanner blind spot being exploited.
- The stale `maistro.goals.model::GoalStatus` ledger row was correctly pruned
  (the gate requires stale entries to be pruned immediately; scan now reports
  19 classified = 19 discovered, EXIT 0).
- `origin/develop` re-fetched first-hand this round: tip unchanged at
  `3c761d14db944a...` — the two-merge grant for a GoalStatus *enum* (PR
  #1938) still has not landed, so the enum shape remains unpassable without
  an external merge; the plain-class shape needs no grant and weakens no gate
  (issue vocabulary, CAS transitions, and terminal-final semantics unchanged
  and re-proven below).

## Validation battery (executed this round, at the finished tree)

- `uv run ruff check .` → All checks passed.
- `uv run ruff format --check .` → 3288 files already formatted.
- `uv run mypy <10 src trees at ci.yml argv>` → Success: no issues in 1057
  files (was 10 errors before this round's fixes).
- `uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541
  argv) → EXIT 0, 19 = 19.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (quality.yml argv) → EXIT
  0, 1323 = 1323, unclassified 0, never_allowlist 0 — no ledger amendment.
- `uv run python scripts/check-m1-convergence-freeze.py --base
  3c761d14db94` (formal-conformance.yml argv) → EXIT 0.
- `uv run python scripts/check-suite-inventory.py` → ok, 17 suites match;
  maistro-core 16335 (baseline 16334 + note's +1).
- `uv run pytest tests/ -q` (the CI `test` job's shipped self-checks, incl.
  `test_the_shipped_ledger_matches_the_shipped_code`) → **5070 passed,
  136 skipped** (rounds 89–97 saw this exact check fail 1f/28p — the
  merge-queue `test: failure`).
- Goals suite with every PG leg enforced
  (`MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN`,
  `MAISTRO_TEST_DATABASE_URL` against a fresh pgvector/pg18 container, port
  15498, removed after) → **71 passed, 0 failed, 0 skipped** — first PG-leg
  execution since the plain-class change; it is the leg that would have
  caught the `pg_store` `.value` defect.
- Alembic on that container: empty → head EXIT 0 ending
  `062 -> 063, The canonical Goal store` with exactly
  `canonical_goals` / `canonical_goal_revisions` /
  `canonical_goal_transitions` among 75 tables; `downgrade 062` drops
  3 → 0; re-upgrade restores 0 → 3.

No gate was weakened and no ledger/grant edited: the only quality-file change
on the branch remains round-97's pruned stale row, required by the gate's own
stale-entry rule once `GoalStatus` stopped being an enum.
