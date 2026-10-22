---
inventory-delta:
  packages/maistro-server/tests: +0
---

# Issue #41 CI-repair round 35: restart E2E seam compatibility

The existing PostgreSQL process-restart test
`packages/maistro-server/tests/test_task_restart_recovery.py` injected a
`run_task` replacement that no longer accepted the production caller's
`governed_egress` keyword. The real restarted server therefore terminalized
the recovered task as failed before the test could verify the canonical Run's
exactly-once recovery contract.

The injected executor now accepts ignored future keyword-only seam arguments.
It still writes the execution marker and returns the same deterministic output,
so the test continues to exercise the production admission, recovery,
lifecycle, receipt, and replay paths rather than asserting a narrower obsolete
call signature.

Validated against a real PostgreSQL 17 container with a forced SIGKILL between
admission and dispatch: the targeted E2E passed (`1 passed`). This changes no
test count.

Follow-up CI-repair validation repeated the PostgreSQL coverage producer against
a fresh local PostgreSQL 17 container: `tests/migrations` passed (107), the
producer's schema-dependent core selection passed (4,919), and the previously
timed-out Canvas selection passed (516). The original Canvas database-drop
timeout therefore did not reproduce.

A later replay on the same isolated PostgreSQL 17 database did reproduce that
teardown timeout once (`DROP DATABASE ... WITH (FORCE)` in
`test_canvas_store_migration.py` exceeded pytest's 30-second timeout), then
passed on an immediate targeted rerun (9) and on a complete fresh producer run:
107 migration tests, 4,930 schema-dependent core tests, and 516 Canvas tests.
The repeatable producer result establishes the PostgreSQL producer portion of
the reported coverage failure, but the intermittent teardown remains an
infrastructure/test-isolation risk. This note does not claim a full
multi-artifact Coverage gate result or resolve #1845's separate
atomic-admission residual.
