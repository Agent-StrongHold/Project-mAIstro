---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# #1199: startup reconciliation raced by two independent OS processes

Scope snapshot: issue #1199 only, branch `auto-1199`, candidate head
`9a86d3e35e7f696b4fd762e405d6183bd29cdac6`, develop base
`e7bc8947335ad66a98c4bf26343037ab4ef96af9`. No production code changed in
this round; the round closes the acceptance items the previous review round
recorded as UNVERIFIED.

## What was UNVERIFIED and what this round executed

The previous round's review left two UNVERIFIED items on
`1199-persisted-projection-delete-ack.md`. Their disposition at this head:

1. **Combined create-projection/compensation failure** — already executed by
   `packages/hive-conductor/backend/tests/test_schedule_projection_authority.py::test_a_create_whose_compensation_also_fails_is_resolved_at_restart`
   (present since the develop base `e7bc8947`). Re-executed at the candidate
   head on all three backends including the real PostgreSQL leg (9 passed,
   see Executed validation). The older note's UNVERIFIED claim predates the
   awareness of that suite's coverage; `1199-persisted-projection-delete-ack.md`
   now carries a reconciliation addendum instead of the stale claim.
2. **Independent-process startup race** — genuinely untested: every existing
   concurrency test (`test_repeated_and_concurrent_startup_is_idempotent`,
   `test_cursors_survive_and_repeated_concurrent_reconciliations_are_idempotent`)
   races callers inside one interpreter with one in-memory store view. Real
   replicas are separate processes whose projection caches only meet through
   the durable store. New test:
   `test_independent_processes_racing_startup_converge_on_canonical_truth`.

## The new test

`packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py::test_independent_processes_racing_startup_converge_on_canonical_truth`
(parametrized memory/sqlite/postgres like its file; skipped on the memory leg
because two processes need durable state to share — hence +3 items, +2
executing legs). The parent installs an un-imported legacy Hive row, then
spawns two real `subprocess` workers. Each worker wires its own
`PersistedStore`/`ModelStore` view of the same shared Hive file and its own
`create_container` Container on the same canonical database (sqlite file or
the fresh PostgreSQL scratch database), signals ready, and waits on a shared
start barrier so both reconciliations genuinely overlap before either runs.
Each runs the shipped `reconcile_schedule_projection()` once. The parent
asserts final durable state after both exit: exactly one canonical identity
carrying the legacy definition, the durable projection repaired from it, the
migration marker durable and single-winner in the shared ledger store
(`version == 1`), and a further reconcile changing nothing. Structural
assertions only — no wall-clock bounds beyond explicit deadlines with
failure messages.

## Executed validation (this round, candidate head 9a86d3e35e)

- `uv run ruff check .` / `uv run ruff format --check .`: passed (3630 files).
- Strict closeout: `MAISTRO_PARITY_MODE=m1-closeout MAISTRO_PARITY_STRICT=1
  uv run pytest tests/cross_product_parity/test_cross_product_parity.py -k
  "schedule_required or schedule_fire or scaffold_only" -q -s`: **3 passed**,
  emitting `M1_PARITY_EVIDENCE {"executed": true, "status": "PASSED",
  "scenario": "scheduler-occurrence-to-conductor"}`.
- Development-mode parity suite: **26 passed**.
- `MAISTRO_TEST_PG_DSN=<lane pg18 :18999> MAISTRO_REQUIRE_PG_LEGS=1 uv run
  pytest packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  packages/hive-conductor/backend/tests/test_schedule_projection_authority.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -q`:
  **116 passed** (real PG legs, including the combined
  create-projection/compensation-failure scenario on all three backends).
- New independent-process test: **sqlite PASSED, postgres PASSED** (memory
  skipped by design), with and without the PG leg required.
- `MAISTRO_TEST_PG_DSN=<lane pg18> uv run pytest packages/maistro-core/tests
  -k schedul -q`: **368 passed**.
- `uv run python scripts/check-suite-inventory.py`: passes with this note's
  recorded `+3` delta.

## Acceptance accounting

Reactivation criterion 4's residual clause — "independent-process import
races and combined create-projection/compensation failure" — is now executed
evidence at the candidate head. The strict #459 configured-lifespan →
Conductor criterion is executed evidence per
`1199-schedule-conductor-closeout-scenario.md` and re-confirmed above in
strict mode.

## Negative-before evidence (develop base e7bc894733, executed this round)

In a detached worktree at the develop base, with the base's own synced
deps, the same strict selection that passes 3/3 at the candidate head was
executed: `MAISTRO_PARITY_MODE=m1-closeout MAISTRO_PARITY_STRICT=1 uv run
pytest tests/cross_product_parity/test_cross_product_parity.py -k
"schedule_required or schedule_fire or scaffold_only" -q -s` → **2 failed,
1 passed**:

- `test_schedule_required_scenario_emits_strict_closeout_evidence` FAILED
  with `ScenarioAbstained: real scheduler (#231) producer -> canonical
  spine -> Conductor boundary is not shipped; the parity harness must not
  recreate it` (`test_cross_product_parity.py:64` at the base) — exactly
  the abstaining scaffold `dee0ba3280` replaced;
- `test_schedule_fire_has_canonical_admission_and_shared_inspection_seams`
  FAILED the same way.

The lane-owned authority suite that carries the projection regressions
(`packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py`)
does not exist at the develop base (`git cat-file -e` at
`e7bc8947335a…`: not in that tree), so the base's negative leg for the
projection authority is the abstaining parity scenario plus the develop
suite's own passing state (the delete/compensation fixes it covers landed
on develop before this base). The worktree was removed after capture; no
base tree file was modified.

## Exact-head revalidation addendum (327f221a67)

The verifier's prior targeted command, `uv run pytest
packages/maistro-core/tests/conftest.py -q -x`, exited 5 because that file
contains no tests. No production regression was exposed; the selector was
invalid. Re-ran relevant acceptance checks at this exact head:

- `uv run pytest packages/hive-conductor/backend/tests -k 'schedule or scheduler' -x -q`:
  **264 passed, 46 skipped**.
- `uv run pytest packages/maistro-core/tests -k schedul -x -q`:
  **321 passed, 47 skipped**. PostgreSQL legs were skipped because
  `MAISTRO_TEST_PG_DSN` is unset in this environment; current-head PG parity
  remains **UNVERIFIED**.
- Strict configured scheduler-to-Conductor evidence:
  `MAISTRO_PARITY_MODE=m1-closeout MAISTRO_PARITY_STRICT=1 uv run pytest
  tests/cross_product_parity/test_cross_product_parity.py -k
  'schedule_required or schedule_fire or scaffold_only' -q -s`:
  **3 passed**, with `executed=true`, `status=PASSED`.
- `uv run python scripts/check-suite-inventory.py`: passed (21 suites).
- `uv run ruff check . && uv run ruff format --check .`: passed (3630 files).

No tests were added in this revalidation, so the existing `+3` inventory
delta is unchanged. Complete PostgreSQL verification was not achievable without
setting up `MAISTRO_TEST_PG_DSN`; this limitation is retained rather than
assuming older-head evidence proves the merged candidate.
