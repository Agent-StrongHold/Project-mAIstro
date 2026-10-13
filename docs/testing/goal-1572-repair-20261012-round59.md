# #1572 repair lane — round 59 verification (2026-10-12)

Head `2f5dd46969fc38b23502d5e40ef35d1f0879ba14`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. HEAD is **ledger-grants-only**
over `a88865c37` (round 58's note head, itself code-identical to
`db091060d` for all production code, migrations and tests): the single diff
is the `maistro.goals.model::GoalStatus` entry in
`quality/ratchet-authorizations.json` plus the trailing-newline restore, so
every rounds 37–58 code/migration result carries byte-identically. This round
independently re-executed the full battery first-hand at the exact dispatch
head rather than inheriting it.

## Driver checks re-run first-hand at this head (all green)

- `uv run ruff check .` — "All checks passed!".
- `uv run ruff format --check .` — 3288 files already formatted.
- 9-file pytest set (driver argv, `result.json` of job
  `f2a6589ce012416d83b304654c599cdd`) — **161 passed, 28 skipped**; the 28
  skips are the PG legs, force-run live below.
- `check-suite-inventory --suite packages/maistro-core/tests` — ok; 16334
  collected node IDs, 0 duplicates, matches the recorded baseline.
- `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94`
  (formal-conformance.yml:77 argv) — **exit 0**, no unapproved architecture
  island (no `GoalRun`, no second executor, no product-private Goal
  lifecycle).

## Acceptance legs re-executed first-hand at this exact head

- **Fresh-database migrations, both majors:** lane containers `auto-1572-pg`
  (pg18, :55712) and `auto-1572-pg17` (pg17, :55717); throwaway databases
  `r59g18` / `r59g17` migrated **empty → head**, final line
  `062 -> 063, The canonical Goal store`; `alembic heads`/`current` = 063
  single head; all three `canonical_goal*` tables present on both majors.
- **Goals + events suites with the PG legs forced live**
  (`MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` +
  `MAISTRO_TEST_DATABASE_URL` — note the two files read different variables;
  both were required for a clean run) at `r59g18`: **453 passed, 0 skipped** —
  conformance across memory/sqlite/postgres, append-only CAS with exactly one
  concurrent winner, stale-revision refusal, subgoal lineage preserving parent
  Goal and Project, foreign Goal indistinguishable from missing, immutable
  `goal_id`/`goal_revision` Run binding, Workspace isolation, schema
  agreement, restart readback.
- **Goals-only at `r59g17`** (second supported major): **70 passed, 0
  skipped**.
- **Downgrade/reapplication** on `r59g18`: `alembic downgrade 062` drops the
  Goal tables (count 3 → 0); `alembic upgrade 063` reapplies (0 → 3).
- **Installed-base upgrades, both majors:**
  `tests/migrations/test_goal_installed_base_upgrade.py` → **8 passed**
  (fresh `r59ib18`, pg18) and **8 passed** (fresh `r59ib17`, pg17): databases
  built by the actual merged develop snapshots `c560d4c` (user-model `056`)
  and `4675101` (planner `057`) plus the HITL `061` forward-upgrade to `063`
  with no stamp edit and no reset; merged identities keep meaning and ancestry;
  facts/keys and a representative Run survive; planner indexes and status
  constraints intact; the three Goal tables read back through the durable
  composition.
- **Production composition re-read:** `container.py:44` import,
  `:273` `goal_store` field, `:276-286` `goal_reader` → `ScopedGoalStore`,
  `:2414` `goal_store = await wire_goal_store(db_pool, pg_pool=pg_pool)`
  inside `create_container`; Hive
  `packages/hive-conductor/backend/adapters/maistro_core.py:195` and
  maistro-server `packages/maistro-server/src/maistro_server/main.py:29`
  compose through `create_container`; `test_goal_wiring.py` (inside the 453)
  proves the shipped Container exposes the store.
- **Ledger hygiene:** `git diff --numstat origin/develop -- quality/` —
  additive-only (17/0, 39/0, 4/0, 6/1); no ledger row lost on either side.

## The CI reds re-proven external, first-hand at this head (unchanged conclusion)

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) → **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization` (19 → 20
  discovered). This is the Quality job's failure.
- `tests/test_check_execution_lifecycles.py` → **1 failed / 28 passed**, the
  failed test `test_the_shipped_ledger_matches_the_shipped_code` running
  `gate.main()` against the real repo — the identical sole finding. This is
  the CI `test: failure` job; the Coverage `combine` step inherits the same
  root suite's single red and contributes no independent deficit.
- **Root cause re-verified in source, not assumed:**
  `scripts/check-execution-lifecycles.py:705 _unauthorized_additions` keeps a
  candidate identity unless it is granted at the trusted base or visible at
  the trusted base; `scripts/ratchet_provenance.py` `load_authorizations`
  (docstring: "a new grant does not take effect in the change that introduces
  it... Authorizing a floor-raise is now two merges — the grant, then the
  regression it permits") resolves grants **from the base revision**.
  `maistro/goals/model.py` does not exist at `3c761d14db94`, so the
  visible-at-base path cannot apply, and the in-branch grant (this head's only
  commit) is a deliberate no-op by construction.
- **Develop sync check:** `git fetch origin`; `origin/develop` still
  `3c761d14db94` == merge-base — nothing to merge, and
  `quality/ratchet-authorizations.json` at origin/develop carries **no**
  GoalStatus grant (keys: `services.rsi::RunStatus`,
  `maistro.graph.nodes.agent_delegate_remote::DelegationStatus` only). The
  two-merge precondition remains unsatisfied upstream.
- **No alternative in-branch path exists:** removing or renaming `GoalStatus`
  would delete a lifecycle the issue's own Scope section specifies
  ("active, satisfied, cancelled, failed, superseded") or smuggle the
  vocabulary past the scanner — a gate-weakening edit, out of bounds. Reusing
  `RunStatus` would make desired state execution state, which both the issue
  ("A Run's outcome never sets Goal state implicitly") and the freeze gate
  forbid.
- **Vulture CI-repair lane empty** at exact CI argv (quality.yml:1079):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323
  reviewed identities → 1323 findings, unclassified 0. Nothing genuinely dead
  to fix and nothing to amend in `quality/vulture-baseline.json`.
- **Dispatch snapshot re-scanned:** the 29 newest comment sources in this
  job's cached snapshot contain no grant/authorization/two-merge language;
  consistent with rounds 37–58 (no maintainer authorization for GoalStatus in
  any comment snapshot).
- **Local-only, not a branch defect:** the branch-independence suite's
  `test_every_quality_json_state_surface_is_classified_once` fails only in
  this worktree because an untracked, gitignored scratch file
  `quality/ac-state.json` (`.gitignore:81`, zero tracked copies) is picked up
  by the unconditional rglob in `scripts/check-branch-independence.py:206`;
  CI passed that test. The scratch file was left untouched (salvage rule).

## Disposition

All issue acceptance criteria are exercised by an executed command or test at
this exact head, first-hand this round. The three CI reds (test / Quality /
Coverage) share exactly one external cause: the GoalStatus
execution-lifecycle grant must land on develop **before** this branch
(two-merge rule, `ratchet_provenance.load_authorizations` reading the base).
No worker in this lane may push or self-grant, so the branch cannot go green
by any in-branch change; the unblocking action is a maintainer grant-only
landing on develop, after which this branch re-queues green with no further
modification. No code, test, or ledger changes this round; no inventory delta.
