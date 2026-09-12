---
inventory-delta:
  packages/maistro-core/tests: +14
---
# Issue 1143 Due-Recovery Isolation

Added behavioral cases to `graph/durable_runs/test_recovery_wakeup.py`:

- a three-candidate due batch continues after an unexpected candidate-local
  failure, keeps the poisoned candidate due, and records a bounded sanitized
  log cause;
- a resolver-factory failure terminalizes the poisoned candidate through the
  durable failed-Run policy;
- an explicitly classified `RecoveryInfrastructureError` aborts the tick
  before later candidates are attempted.
- a resolver-factory failure persists the stable `NodeResolverUnavailable`
  message on the failed Run, never the factory's own error text;
- `_lazy_resolver` keeps the factory error attached as `__cause__`;
- `_sanitized_cause` redacts quoted keys, `Authorization`/`Bearer` headers,
  and provider-style key literals (eight parametrized cases) while leaving
  plain text untouched.
