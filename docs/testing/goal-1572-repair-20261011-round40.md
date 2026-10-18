# #1572 round-40 verification record (2026-10-11, head fe8676d7044f, base 3c761d14db94)

Independent verifier round. The prior driver job (`02ada13df…`) died on a
provider timeout AFTER all five deterministic checks returned 0 — this round
re-executed every check first-hand and completed the acceptance validation the
dead agent never reported. No code, test, or ledger changes; no inventory delta.

## Driver checks re-executed (first-hand, exact argv)

| check | result |
|---|---|
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 3288 files already formatted |
| driver 9-file pytest set `-q -x` | 161 passed, 28 skipped (PG legs off) |
| `check-suite-inventory.py --suite packages/maistro-core/tests` | ok, matches recorded inventory |

## Issue acceptance — executed first-hand this round

- **Goals suite, PG legs enforced**: fresh databases on both supported majors
  (`v40g18` on pgvector:pg18 :55712, `v40g17` on pgvector:pg17 :55717),
  `DATABASE_URL`-driven `alembic upgrade head` empty→**063 (head)** each, then
  `pytest packages/maistro-core/tests/goals` with `MAISTRO_REQUIRE_PG_LEGS=1`
  and both DSN vars set → **70 passed, 0 skipped on pg18 AND pg17**. All seven
  conformance criteria (round-trip, append-only + CAS one-winner, subgoal
  lineage + recorded reassignment, lifecycle CAS/terminal-final, two-principal
  isolation, foreign==missing, missing-goal refusal) ran on all three backends.
  Operator note: the legs read TWO env vars — `MAISTRO_TEST_DATABASE_URL`
  (schema agreement, installed-base) and `MAISTRO_TEST_PG_DSN` (conformance,
  run binding) — and the PG legs require a migrated database; a shared,
  unmigrated database surfaces as errors, not skips.
- **Catalog**: `\dt canonical_goal*` on v40g18 → exactly `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions`; `alembic_version`
  = 063.
- **Migrations**: `pytest tests/migrations/test_goal_installed_base_upgrade.py
  tests/migrations/test_migration_chain.py` with PG DSNs → **26 passed**
  including the installed-base walks from real develop snapshots `c560d4c`
  (→056) and `4675101` (→057), forward-upgraded to candidate 063 with no stamp
  edit, merged-identity preservation, byte-identical restored files, row
  survival, and planner status CHECKs. The 043 diff vs develop is
  docstring-only (no DDL/identity change).
- **Restart readback**: `test_goal_restart_readback.py` (write, close, reopen,
  assert Goal/revision chain/bound Run provenance) — green in the 70/70.
- **Production composition**: `create_container` wires `goal_store`
  (container.py) and derives the authorized `goal_reader`; Hive adapter
  (`packages/hive-conductor/backend/adapters/maistro_core.py:195`) and
  maistro-server (`packages/maistro-server/src/maistro_server/main.py:344`)
  both compose through it; `test_goal_wiring.py` proves exposure on the shipped
  Container — green.
- **Convergence freeze**: `check-m1-convergence-freeze.py --base
  3c761d14db94` → exit 0 (no GoalRun/OrchestratorRun/second executor).
- **Closure keywords**: none in the PR body or any branch commit message
  (grep over `git log 3c761d14..HEAD`).

## Sole remaining blocker — external, unchanged

`check-execution-lifecycles.py` → exit 1 with the single finding
`maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
trusted base and has no already-landed authorization`. Verified structural,
not repairable in-branch: `scripts/ratchet_provenance.py:478` reads
authorizations **from the base revision** (two-merge rule, self-grants unread
by design); develop's ledger has 0 GoalStatus rows; `git ls-remote` confirms
origin/develop is still exactly `3c761d14db94`. CI's `test` job red reduces to
the same root cause (`tests/test_check_execution_lifecycles.py::
test_the_shipped_ledger_matches_the_shipped_code` asserts `gate.main()==0`).
The quality-gate CI red is this same gate; the coverage-gate red is inferred
to follow from the test job's missing artifacts (not independently executed).
Unblock: land the GoalStatus execution-lifecycles authorization on develop as
a grant-only commit (outside this lane's authority), then resync auto-1572.

Cosmetic note, not repaired (docs-only, no behavior): the new ci.yml goals
step's comment says "migration 062"; the Goal tables ship in 063.
