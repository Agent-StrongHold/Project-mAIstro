---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Issue #1247 — org-bound global memory requires caller context

Adds one behavioral regression test covering both the Python scope matcher and
compiled SQL predicate: an org-bound global memory is hidden from a caller
without organization context, while an unbound global remains visible.
