---
inventory-delta:
  packages/maistro-server/tests: +20
---
# Project scope API inventory delta

Adds 20 collected `maistro-server` node IDs for the canonical Project administration surface introduced by #561. The new cases cover Workspace-scoped Project reads and structural administration, cross-Workspace hiding, cycle and deletion guards, delegated-grant authorization semantics, invalid permission shapes, whitespace-only Project identity inputs, and fail-closed behavior when the canonical Project store is unavailable.
