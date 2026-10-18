---
inventory-delta:
  packages/maistro-core/tests: +1
---

# 1845-task-admission-completion-fault-recovery

Adds the native #1845 regression to
`packages/maistro-core/tests/tasks/test_idempotency_durable.py`.

The test injects a failure in the idempotency completion write *after* a
file-backed SQLite canonical Run has committed. It closes both the Run and
claim stores, recreates them over the same database, advances past the pending
lease, and retries the same scoped key and payload. The retry must attach the
committed Run to the old claim and return the original task/run identities; it
also asserts that exactly one durable queued Run exists. This distinguishes
claim completion recovery from the prior in-memory mocked-completion test.
