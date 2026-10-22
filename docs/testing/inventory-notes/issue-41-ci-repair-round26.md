---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 26: coverage-gate reproduction and residual boundary

No source or test was changed. The assigned CI failure named the coverage gate,
but this job directory's only supplied check log (`check-1.log`) says `All
checks passed!` and does not identify a failed producer or source line. A
speculative coverage edit would not address that missing evidence.

At `8efa6a4eb`, local coverage reproduction passed:

- the full core producer passed: `11736 passed, 785 skipped, 1 xfailed`;
- the server and conductor producers passed: `499 passed, 8 skipped` and
  `3311 passed, 6 skipped` respectively;
- `scripts/check-diff-coverage.py` against base
  `1e4933e2a1b7a0bc1bdecfdbafca846c7cb458f4` passed every measured changed
  file at the 90% line / 80% branch floors; and
- the publish-set coverage invocation (core, canvas, evolve, RSI and bootstrap
  source roots) passed its exact 87% floor at **91%**.

A fresh PostgreSQL 18 database was migrated through revision 051 and ran
`test_idempotency_durable.py` with `MAISTRO_TEST_PG_DSN`: `28 passed`. The
focused task/chat admission suite on that database passed: `93 passed`.
`ruff check .`, `ruff format --check .`, and the exact vulture baseline command
also passed.

This validates the reported coverage repair path without changing the tree. It
does **not** close #41: `TaskQueue._admit_claimed` still creates the Run before
calling the separately scoped idempotency completion write, and the real
PostgreSQL test exercises claim rows only, not a completion-write fault across
independent Run and claim transactions. The issue snapshot assigns that atomic
admission/process-kill/multi-replica proof to #1845/#1325; this lane must not
invent a competing implementation.
