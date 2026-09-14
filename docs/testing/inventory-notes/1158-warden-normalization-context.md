---
inventory-delta:
  packages/maistro-core/tests: +10
---
# #1158 Warden normalization and bounded context

- Warden regression coverage now exercises spaced-letter and bounded leetspeak
  instruction overrides, cross-turn reconstruction, trusted-context exclusion,
  and the turn/byte aggregation budget.
- The harness safety seam verifies that an override reconstructed from two
  untrusted turns is refused before the inner provider receives the messages.
