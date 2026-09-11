---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Issue 1143 Due-Recovery Isolation

Added three behavioral cases to `graph/durable_runs/test_recovery_wakeup.py`:

- a three-candidate due batch continues after an unexpected candidate-local
  failure, keeps the poisoned candidate due, and records a bounded sanitized
  log cause;
- a resolver-factory failure terminalizes the poisoned candidate through the
  durable failed-Run policy;
- an explicitly classified `RecoveryInfrastructureError` aborts the tick
  before later candidates are attempted.
