---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #1196 canonical Invocation quota admission

Six behavioral tests cover quota reservation before dispatch, reserve exhaustion through
an alternate effect strategy, atomic concurrent admission, rollback/unknown-outcome
reconciliation, shared SQLite replica admission, and the governed Agent LLM adapter. The
tests use real canonical Invocation calls and assert the secret-free Workspace/principal/
provider quota evidence persisted on each Invocation.
