---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 147-delegation-receipt

Adds one regression case covering a cross-instance peer response that claims
submission without returning an A2A `task_id`. The delegate node now refuses to
pause or create a child Run because the child would have no receipt with which
to correlate a later result.
