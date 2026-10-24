---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +8
  packages/maistro-server/tests: +1
---
# 1084 model egress convergence

Added coverage for the Container's active model Binding/client bootstrap and real governed client dispatch, compatibility-client Invocation recording with Run/NodeRun/Attempt execution correlation and selected provider metadata, and the embedded runtime handing the agent roster the Container's canonical model client. The Hive adapter test composes the shipped builder with a real Container and verifies its Invocation ledger. Conductor identity tests pin that a governed completion without an explicit tuple consumes the ambient persisted Run/NodeRun/Attempt, and the server seam test pins that the chat door's conductor supplies no fixed stand-in tuple.

SPEC-285 addendum: four core tests pin incremental streaming through the governed Invocation — live chunk delivery while the wire is still producing (structural handshake, not wall-clock), mid-stream failure terminalizing non-COMPLETED and reaching the consumer, consumer abandonment terminalizing UNKNOWN, and deduplicated replay without re-dispatch. The Hive adapter test pins the shipped streaming port landing on the Invocation ledger with the terminal usage chunk's accounting.
