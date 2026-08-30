---
inventory-delta:
  packages/maistro-core/tests: +2
---

# M1 #332 cancellation terminalization evidence

This change adds two focused tests: one proves a client disconnect observes the already-cancelled canonical Run without a false terminalization warning, and one proves the cancellation close contract rejects a contradictory failure payload before mutating Run state.
