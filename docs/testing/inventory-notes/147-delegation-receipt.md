---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 147-delegation-receipt

Covers a cross-instance peer response that claims submission without returning
an A2A `task_id`. The delegate node retains the reserved child Run and parks on
the system-owned reconciliation pause; it does not advance the parent as a
completed failed delegation before the transport receipt is recovered or its
deadline expires.
