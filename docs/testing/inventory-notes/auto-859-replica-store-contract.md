---
inventory-delta:
  packages/maistro-turing/backend/tests: +1
---

# #859 explicit replica-safe state-store contract

A multi-replica declaration now requires the composed `SelfModelStateStore` to
explicitly declare `is_shared_across_replicas = True`. Passing any store object
is not treated as proof of shared durable authority: the process-local store
and unclassified/custom stores are rejected, while the shared fake store
exercises the declared integration seam. The additional regression test pins
that the explicit local store cannot bypass the replica guard.
