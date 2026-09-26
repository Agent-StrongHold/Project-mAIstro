---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/hive-conductor/backend/tests: +1
---

# #53 Conduit-backed conversation execution

Adds focused evidence that conversation-only turns invoke the canonical Conduit
before the Run Attempt and that Hive's unavailable StubAgentPort cannot be
bypassed by a callback that returns a success-shaped answer.
