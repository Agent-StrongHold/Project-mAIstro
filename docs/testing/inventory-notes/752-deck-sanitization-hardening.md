---
inventory-delta:
  packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts: +1
---
# #752 Deck sanitization hardening

The Deck browser corpus adds one regression case for CSS escape/comment
obfuscation and active SVG/embedded-content families. It runs against the real
Deck Builder component mounted by the ephemeral browser harness, and asserts
that the attacker receives no request and no script marker is set while safe
text and presentation SVG remain.
