---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# Issue #1086 governed Canvas model egress coverage

The Canvas route tests now exercise the shipped route's composition fallback with
canonical Run/NodeRun/Attempt state and verify that provider refusal settles the
owning Attempt instead of returning a score-shaped success. They also cover
successful Attempt settlement with parsed quality evidence and malformed provider
responses failing the owning Attempt after the Invocation completes. Adapter
coverage proves that Hive production settings carry provider metadata and explicit
model Bindings into the canonical maistro-core Container.
