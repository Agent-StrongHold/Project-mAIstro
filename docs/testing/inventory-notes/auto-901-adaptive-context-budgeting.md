---
inventory-delta:
  packages/maistro-core/tests: +3
---
# #901 Adaptive context budgeting exploration

Exploratory spike for epic #901's "adaptive top-k/context budgeting" leaf: an
`AdaptiveContextAssemblyPolicy` subclass scales the context budget by query
length (longer query -> larger budget) and the tests prove that scaling
actually reaches the production inclusion decision — a memory below
`ALWAYS_INCLUDE_WEIGHT` flips from dropped to kept when the adaptive budget
grows past its whole-memory cost (ADR-091 `_pack` semantics).

One test is a control (the default policy at the same base budget keeps the
memory the adaptive policy dropped), and one pins the production budget gate
itself: a budget-band memory is included only while it fits whole, while an
always-include memory survives a budget that drops it. All assertions are
token-arithmetic deterministic (4 chars/token), no timing or ordering
sensitivity. No production code changed: experimental policies stay out of
the canonical memory authority, per the epic's contract.
