---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# #752 Deck sanitization hardening

The Deck browser corpus adds regression cases for CSS escape/comment
obfuscation, active SVG/embedded-content families, and re-sanitization of edited
DOM state. It runs against the real Deck Builder component mounted by the
ephemeral browser harness in preview and presentation modes, and asserts that
the attacker receives no request and no script marker is set while safe text and
presentation SVG remain. The `+0` ledger delta is intentional: this TypeScript
Playwright suite is not part of the pytest collection inventory.
