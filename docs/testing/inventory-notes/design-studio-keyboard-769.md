---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# Design Studio keyboard journey (#769)

Adds Playwright journeys that walk every supported Design Studio artifact mode
from the real page tab order, activate native controls with keyboard commands,
and verify fixed-page and Deck editor transitions. The mode journey also runs
axe against the Design Studio main region without excluding color contrast.
The `+0` delta is intentional: this browser-only suite is not collected by
pytest, so its node count is not part of the inventory ledger.
