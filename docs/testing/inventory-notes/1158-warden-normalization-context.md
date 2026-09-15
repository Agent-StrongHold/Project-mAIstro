---
inventory-delta:
  packages/maistro-core/tests: +13
---
# #1158 Warden normalization and bounded context

- Warden regression coverage now exercises spaced-letter, composed spaced-leetspeak,
  and bounded leetspeak instruction overrides, cross-turn reconstruction, trusted-context exclusion,
  and the turn/byte aggregation budget.
- The harness safety seam verifies that an override reconstructed from two
  untrusted turns is refused before the inner provider receives the messages.
- ReAct tool-result coverage verifies ordered cross-call aggregation, and the
  message-context regression verifies the tail and per-item serialization caps.
