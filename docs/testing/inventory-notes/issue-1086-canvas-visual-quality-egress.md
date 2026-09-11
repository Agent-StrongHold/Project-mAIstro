---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# Issue 1086 Canvas visual-quality egress

The shipped `/v1/canvas/eval` route now has product-composition coverage for a
successful governed quality evaluation and for missing, fabricated, or
unauthorized execution context. The success test builds the egress from the
application engine composition and asserts one completed Invocation carries
the canonical Workspace/Project/Run/NodeRun/Attempt correlation while
preserving JSON score parsing. Refusal tests prove unavailable evaluations do
not return a fake score.
