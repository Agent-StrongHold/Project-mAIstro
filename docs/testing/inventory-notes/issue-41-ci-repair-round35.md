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
test count. The full PostgreSQL coverage producer was not established in this
round: its unrelated Canvas leg timed out while dropping its isolated database,
so the reported coverage-gate failure remains unverified rather than being
attributed to this issue.
