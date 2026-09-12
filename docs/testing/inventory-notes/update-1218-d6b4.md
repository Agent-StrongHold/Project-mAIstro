---
inventory-delta:
  packages/maistro-core/tests: +1
---
# update-1218-d6b4

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

The repair adds `test_route_request_preserves_supplied_auth` to cover the
refactored auth-resolution helper's explicit-identity branch while preserving
the canonical security boundary behavior.
