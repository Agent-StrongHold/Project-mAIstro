---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Issue 1058 canonical-store gap repair

Adds two-Workspace regressions against the spine-backed
`CanonicalDurableRunStore` itself and the in-memory store: direct
answer/timeout/cancel mutations carrying a foreign Workspace's authorization
are refused at each store's `_mutate` boundary (before any deadline logic can
mask the refusal), and a scoped expiry tick never settles the foreign Run.
Existing two-Workspace tests drove settlement past the pause deadline, so a
removed membership predicate could hide behind `HitlDeadlineElapsed`; these
pin the `KeyError` refusal itself.
