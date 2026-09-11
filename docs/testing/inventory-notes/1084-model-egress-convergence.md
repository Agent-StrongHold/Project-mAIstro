---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests/capabilities: +4
---
# 1084 model egress convergence

Added coverage for the Container's active model Binding/client bootstrap and real governed client dispatch, plus compatibility-client Invocation recording with Run/NodeRun/Attempt execution correlation and selected provider metadata. The Hive adapter test composes the shipped builder with a real Container and verifies its Invocation ledger.
