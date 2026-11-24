---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# 1199-repair-legacy-principal-chain-tip

Repair round for the #1199 lane at starting head `aba6fe1365ce0e2388fe74459cb99a0d2388e216`
(develop base `c87dd79acd2a0df83ad2030e18613259899bcd14`). No test function
was added or removed; this note records a missed chain-tip reconciliation and
the full validation battery re-executed after it.

## The failure (negative-before, executed)

`MAISTRO_TEST_DATABASE_URL`/`MAISTRO_TEST_PG_DSN` against the lane-owned
`auto-1199-r3-pg` (pgvector/pg18 at 127.0.0.1:18995, `maistro_test`
migrated to head):

    uv run pytest tests/migrations -q
    -> 3 failed, 170 passed

All three failures — `TestMixedDataMigratesLosslessly`,
`TestForcedProcessDeathIsRestartReconcilable`, `TestTwoReplicasConverge` —
funnel into `_assert_losslessly_migrated()`, whose closing chain-tip pin
(`tests/migrations/test_legacy_principal_ownership_live.py:506`) still
asserted `{"068"}`:

    AssertionError: assert {'069'} == {'068'}

Root cause: the develop-sync renumber (see
`1199-develop-sync-33ac30c5-renumber-069.md`) reconciled
`test_capability_invocation_effect_index_migration.py`,
`test_goal_installed_base_upgrade.py` (CHAIN_HEAD) and
`test_migration_chain.py` onto the new `069` tip but missed this fourth
chain-tip pin. `upgrade head` runs 068 *and* the schedule-deletion revision
069, so every converged-assertion in this suite failed against the branch's
own chain — a genuine candidate regression, not an infrastructure flake.

## The repair (positive-after, executed)

The pin moves to `{"069"}` under the same convention the other three suites
already recorded: landed trunk identities never move — 068 keeps its
subject, asserts and fixture stamps (`PRE_068_VERSIONS == {"067"}` is
unchanged and still the correct pre-migration state) — and the renumbered
`069_schedule_deletions` appends as the single new head. One comment block
changed with it; no production code was touched.

- `uv run pytest tests/migrations/test_legacy_principal_ownership_live.py -q`
  — **3 passed** (was 3 failed).
- `MAISTRO_TEST_DATABASE_URL`/`MAISTRO_TEST_PG_DSN` full re-run:
  `uv run pytest tests/migrations -q` — **173 passed, 0 skipped** — the
  SIGKILL-mid-migration rollback/converge leg and the two-replica advisory-
  lock convergence leg included.

## Full battery re-executed this round (same server, exact candidate head)

- `uv run ruff check .` — All checks passed; `uv run ruff format --check .`
  — 3630 files already formatted.
- `MAISTRO_TEST_PG_DSN=…maistro_test uv run pytest
  packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  test_schedule_projection_authority.py test_schedule_canonical_definitions.py
  -q` — **122 passed, 1 skipped** (the memory leg of the two-process race,
  by design: both durable legs pass).
- Same DSN, `packages/maistro-core/tests/scheduling -q` — **327 passed**;
  `packages/maistro-core/tests -k schedul -q` — **368 passed**.
- Same DSN, nine adjacent Hive scheduler suites (scheduler, bounded tick,
  canonical admission, canonical due, frequency floor, scope, workspace
  scope, timezone health, manual fire canonical) — **172 passed**.
- `MAISTRO_PARITY_MODE=m1-closeout MAISTRO_PARITY_STRICT=1 … -k 'schedule_required
  or schedule_fire or scaffold_only'` — **3 passed**, emitting
  `M1_PARITY_EVIDENCE {"executed": true, "scenario":
  "scheduler-occurrence-to-conductor", "status": "PASSED"}`; the full
  parity suite — **26 passed**.
- mypy over the seven library `src` trees — no issues in 960 files.
- Gates: CI-exact vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) — 1221 reviewed identities = 1211 findings, exit 0;
  suite inventory — 21 suites match; test duplicates — 0 groups; durable
  table inventory — 125 tables; doc links; backlog consistency — all exit 0.

The prior addendum's `InvalidPasswordError` was an environment credential
gap, not a product failure: this round re-ran every PostgreSQL leg with the
lane server's actual credentials and all of them executed (none skipped
except the by-design memory leg).
