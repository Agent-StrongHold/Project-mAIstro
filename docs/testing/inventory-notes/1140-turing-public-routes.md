---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-turing/backend/tests: +3
  tests/: +18
---
# Turing public-route gate inventory

Issue #1140 adds shared Conductor/Turing route-policy fixtures covering protected and public declarations, missing declarations, expired exemptions, exact-route lookalikes, ambiguous runtime declarations, and trusted-base policy ratcheting (+18 collected cases and three Turing runtime authorization cases). The fixtures now audit both live FastAPI route trees, including lazy nested routers and WebSocket routes. The shared runtime matcher is used by both backends and the gate; Conductor's suffix carve-outs are removed so an undeclared or misleading route cannot become authenticated-only by name.
