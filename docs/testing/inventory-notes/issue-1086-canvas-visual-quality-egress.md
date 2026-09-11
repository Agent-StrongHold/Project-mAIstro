---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# Issue 1086 Canvas visual-quality egress

The shipped `/v1/canvas/eval` route now has product-composition coverage for a
successful governed quality evaluation and for missing canonical execution or
Binding context. The success test asserts one completed Invocation carries the
supplied Workspace/Project/Run/NodeRun/Attempt correlation and preserves the
existing JSON score parsing. The refusal tests prove unavailable evaluations do
not return a fake score.
