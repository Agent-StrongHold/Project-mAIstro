---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/maistro-canvas/tests: +0
---

# Issue #41 CI-repair round 31: targeted PostgreSQL validation

No production or test code changed. This validation-only closeout follows the
stale merge-conflict syntax failure recorded in the supplied prior driver log:
current `ruff check .` passes, and the exact vulture baseline command reports
1,342 reviewed identities and no unbanked identity.

Against the existing local `auto41-coverage-pg` PostgreSQL 17 service,
`MAISTRO_REQUIRE_PG_LEGS=1` made the durable idempotency producer execute its
otherwise skipped leg: `packages/maistro-core/tests/tasks/test_idempotency_durable.py`
passed 28 tests. The focused spine/API producer passed 263 tests (118 expected
skips), and the Canvas migration producer passed 9 tests with its PostgreSQL
legs required. This independently shows the earlier Canvas teardown timeout is
not reproduced by that isolated module; it does **not** prove the full combined
coverage workflow, which still needs all three CI coverage producers and their
artifact combine step.

The acceptance review remains deliberately unchanged. `TaskQueue._admit_claimed`
still commits the canonical Run through `_mint` and performs the idempotency
completion write afterwards (`packages/maistro-core/src/maistro/tasks/queue.py`).
The SQLite recreation regression passes, but it is not the required PostgreSQL
joint Run+binding transaction, process-kill, or multi-replica proof. The issue
snapshot assigns that residual to #1845/#1325/#1855, so this validation round
does not introduce a parallel admission design or claim parent closeout.
