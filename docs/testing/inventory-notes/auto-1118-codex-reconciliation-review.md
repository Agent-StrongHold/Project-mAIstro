---
inventory-delta:
  packages/maistro-core/tests: +7
---
# #1118 review: scope-first, lock-free provider lookup, legacy rows, events, usage, UTC

Seven behavioral cases in `capabilities/test_invocation_reconciliation.py`:

- the caller's scope is checked before a terminal Invocation is returned;
- a provider adapter is consulted outside the effect lock (an unrelated
  Invocation crosses the boundary meanwhile) and its evidence is refused when
  the row's revision moved while it was away;
- pre-scope rows (no Workspace/Project on the row or its Binding) are
  reconcilable: manual evidence backfills the scope, provider evidence settles
  with an unscoped audit record;
- the governed service announces `capability.invocation.completed`/`failed`
  after a reconciliation, idempotently;
- provider evidence carries recovered `InvocationUsage` into the APPLIED row;
- naive timestamps (a `datetime.now()` cutoff, a row stored without an offset)
  are read as UTC by discovery.
