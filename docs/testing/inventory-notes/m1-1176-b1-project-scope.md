---
inventory-delta:
  packages/maistro-core/tests: +2
---
# m1-1176-b1-project-scope

The admission scope regression suite now proves that the same principal,
Workspace, action, and textual key cannot reconcile across distinct Projects,
and that two queues using distinct canonical Project bindings mint distinct
Runs. The queue derives the effective Workspace/Project binding from the
canonical Run admitter before claiming, so the idempotency key cannot reuse a
Run filed in a different Project.
