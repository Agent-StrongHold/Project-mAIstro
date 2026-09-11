---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #1196 canonical Invocation quota admission

Four behavioral tests cover quota reservation before dispatch, reserve exhaustion through
an alternate effect strategy, atomic concurrent admission, and rollback/unknown-outcome
reconciliation. The tests use real `InvocationExecutionService` calls and assert the
secret-free Workspace/principal/provider quota evidence persisted on each Invocation.
