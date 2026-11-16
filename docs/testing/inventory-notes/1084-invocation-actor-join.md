---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +1
---
# Issue #1084 — chat/voice Invocation carries the admitted Run's actor

Two maistro-core node IDs pin the compatibility client's actor seam:
`GovernedModelChatClient` forwards `actor_id` from the model execution
context to `ModelChatEgress.complete`, and a caller that supplies no actor
still records `""` — the ledger's own no-actor reading, never a fabricated
principal.

One hive-conductor node ID proves the join end to end through the shipped
`/v1/chat/complete` route on a real embedded Container: the turn's single
completed Invocation is correlated to the Run it was admitted under and
carries the same authenticated principal that admission recorded on the Run
(read from the persisted ledger; nothing is seeded or mocked). The existing
voice-intent test gained the same Invocation-level actor assertion.
