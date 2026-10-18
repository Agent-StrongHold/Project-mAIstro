---
inventory-delta:
  packages/maistro-server/tests: +22
---
# Project scope API inventory delta

Adds 22 collected `maistro-server` node IDs: 20 for the canonical Project administration surface introduced by #561 — Workspace-scoped Project reads and structural administration, cross-Workspace hiding, cycle and deletion guards, delegated-grant authorization semantics, invalid permission shapes, whitespace-only Project identity inputs, and fail-closed behavior when the canonical Project store is unavailable — plus 2 for the #1148 membership-revocation route: a Workspace owner gets 204 and the row is gone, a non-owner gets 403 and the row survives.
