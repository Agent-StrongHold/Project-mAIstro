---
inventory-delta:
  packages/maistro-core/tests: +5
---

# Issue 1118 invocation reconciliation

The focused reconciliation tests add evidence for the canonical Invocation recovery
lifecycle: stale `RUNNING` discovery after a simulated process death, applied
settlement without provider re-dispatch, provider evidence for both applied and
not-applied outcomes, fail-closed indeterminate evidence, SQLite reopen durability, and cross-service retry gating. They also verify
that operator audit records retain actor, reason, scope, and Run/NodeRun/Attempt/
Invocation correlation.
