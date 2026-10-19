# #1572 round-39 verification record (2026-10-11, head 632a89a31128, base 3c761d14db94)

Round-38 verdict re-verified first-hand; nothing was trusted. No code, test, or
ledger changes resulted; no inventory delta. The prior dispatch's "BLOCKED"
block resolved as a provider timeout in the previous driver job
(`16b0cbbd…`: `error: provider error … Request timed out` with all five
deterministic checks returncode 0) — not a check failure.

## Driver checks re-executed (exact argv)

| check | argv | result |
|---|---|---|
| 0 | `uv sync --locked --extra dev` | ok (re-ran; then `--all-extras` for the mypy parity below) |
| 1 | `uv run ruff check .` | All checks passed! |
| 2 | `uv run ruff format --check .` | 3288 files already formatted |
| 3 | driver's 9-file pytest set `-q -x` | 161 passed, 28 skipped (identical to driver log) |
| 4 | `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | ok, matches recorded inventory |

## Issue acceptance — all re-executed this round

- **Three-backend conformance round-trip**: `pytest packages/maistro-core/tests/goals`
  with `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` set and
  `MAISTRO_REQUIRE_PG_LEGS=1` → **70 passed, 0 skipped** on PostgreSQL 18.6 and
  PostgreSQL 17.11 (in-memory/SQLite/PG params all active).
- **Append-only revisions, stale refusal, CAS one-winner**: covered inside the
  same conformance suite (refuses stale `expected_revision`, terminal states
  refuse) — green in the 70/70.
- **Subgoal lineage + explicit recorded agent reassignment**:
  `reassign_agent` readback in `test_goal_restart_readback.py` — green.
- **Run binding immutable after admission**: `test_run_goal_binding.py`
  `[postgres]` legs — green (see concurrency note below for an operator-induced
  transient).
- **Workspace isolation, foreign Goal ≡ missing Goal**: conformance suite
  through `ScopedGoalStore` — green.
- **Production composition (Hive + maistro-server)**:
  `test_goal_wiring.py` — green, including the bare-database `wire_goal_store`
  bring-up on a throwaway PG database.
- **Restart readback of Goal/revisions/bound Run provenance**:
  `test_goal_restart_readback.py` — green (file-backed durable composition).
- **No second execution identity**: `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94…`
  → "no unapproved new architecture island", exit 0.

## Migration identity — all four installed-base legs executed fresh this round

Read-only snapshots extracted via `git archive` (no git metadata mutation):
c560d4c (develop through user-model `056`, parent `043_invocation_quota_door`)
and 4675101 (through planner `057`, parent `056`); candidate head is `063`,
`down_revision = "062"` (develop's integrated head) — merged identities
preserved, no reassignment.

| fixture | engine | result |
|---|---|---|
| c560d4c empty→056 → populated (fact, statement key, ws/project/run) → candidate `upgrade head`, no reset, no stamp edit | pg18.6 | 056→…→063 ran; 3 `canonical_goal*` tables; fact/key/run rows survived unchanged; `ix_canonical_runs_status_created` present; version 063 |
| same | pg17.11 | same (7 upgrade steps), data survived |
| 4675101 empty→057 → populated run → candidate `upgrade head` | pg18.6 | 057→…→063; `ck_canonical_runs_status` + `ck_canonical_node_runs_status` intact; run survived; version 063 |
| same | pg17.11 | same (6 steps), constraints intact |

Fresh-install: empty→063 on both majors (single linear head `063`), and
downgrade 063→062 drops exactly the three Goal tables then 062→063 reapplies
(executed on r39g18/pg18.6).

Fixture note: the first 056-fixture upgrade failed on
`ck_canonical_runs_status` because the probe Run was inserted with an
uppercase `status`; the CHECK is added by **develop's own merged 057**
(`_add_check_constraint_if_absent`), so develop's own 056→057 upgrade would
reject that row too. Re-inserted with the store's real vocabulary
(`completed`) — not a candidate incompatibility.

## Gates

- vulture at CI argv (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  exit 0, 1323 = 1323; **no amendment applies**.
- `mypy --strict packages/maistro-core/src`: **789 files clean** — but only
  after `uv sync --locked --all-extras`, matching quality.yml's job setup
  (`uv sync (full dev deps)`); with `--extra dev` alone there are 5
  `maistro_bootstrap.*` import-not-found errors, environment skew, not branch
  defects.
- execution-lifecycles: **exit 1, sole finding**
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization`. Branch candidate
  ledger carries exactly one DOMAIN row with rationale; develop
  (`origin/develop` re-fetched this round, still `3c761d14db94`) carries zero.
  Mechanically re-proven: the **unmodified** gate `main()` with only a
  GoalStatus grant injected at `load_authorizations` (what a grant-only
  develop landing provides) exits 0 with all 20 vocabularies classified
  (3 CANONICAL, 8 CONVERGE, 7 DOMAIN, 2 PROJECTION). Two-merge rule: no
  in-branch edit can legitimately flip this gate; the sole unblock is the
  grant-only develop landing, outside this lane's GitHub authority.

## Operator-transient (recorded, not repaired)

Running the goals suite **concurrently** with
`check-suite-inventory.py --suite packages/maistro-core/tests` against the
*same* PG database tripped the real per-principal active-root-Run ceiling
(`RunConcurrencyExceeded: 8 active, limit 8`): 8 `created` runs accumulated
from the two processes sharing r39g18. The ceiling is production behavior
working as designed; the collision is a lane-environment artifact (CI gives
each job its own database; the driver's check-3 runs without a PG DSN).
Database dropped and rebuilt empty→063; subsequent sequential run: **70/70**.
Not reproduced when runs are sequential.

## Residual action

The single remaining merge-queue red is the external GoalStatus
execution-lifecycles grant on develop. Everything reachable from this branch
is green above.
