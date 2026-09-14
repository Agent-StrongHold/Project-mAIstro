---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-turing/backend/tests: +3
  tests/: +15
---
# Turing public-route gate inventory

Issue #1140 adds shared Conductor/Turing route-policy fixtures covering protected and public declarations, missing declarations, expired exemptions, exact-route lookalikes, ambiguous runtime declarations, and trusted-base policy ratcheting (+15 parametrized collected cases and three Turing runtime authorization cases). The shared runtime matcher is used by both backends and the gate; Conductor's suffix carve-outs are removed so an undeclared or misleading route cannot become authenticated-only by name.
