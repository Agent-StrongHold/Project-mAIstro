---
inventory-delta:
  packages/maistro-turing/backend/tests: +1
  tests/: +10
---
# Turing public-route gate inventory

Issue #1140 adds shared Conductor/Turing route-policy fixtures covering protected and public declarations, missing declarations, expired exemptions, and suffix lookalikes (+10 parametrized collected cases and one Turing runtime default-deny case).
