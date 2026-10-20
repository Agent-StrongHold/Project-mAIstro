---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +4
  packages/maistro-server/tests: +1
---
# 1084 model egress convergence

Added coverage for the Container's active model Binding/client bootstrap and real governed client dispatch, compatibility-client Invocation recording with Run/NodeRun/Attempt execution correlation and selected provider metadata, and the embedded runtime handing the agent roster the Container's canonical model client. The Hive adapter test composes the shipped builder with a real Container and verifies its Invocation ledger. Conductor identity tests pin that a governed completion without an explicit tuple consumes the ambient persisted Run/NodeRun/Attempt, and the server seam test pins that the chat door's conductor supplies no fixed stand-in tuple.
