---
inventory-delta:
  packages/hive-conductor/tests/e2e: +1 browser test
---
# Design Studio keyboard journey (#769)

Adds one Playwright journey that walks every supported Design Studio artifact
mode from the real page tab order, activates each native button with Enter,
and verifies the pressed state, live mode announcement, and prompt label update.
The journey also runs axe against the Design Studio main region (excluding the
repository's documented color-contrast palette findings). The existing baseline
journey was already present on the starting develop head; this test extends it
from two modes to the complete current picker and checks the newly exposed
keyboard instructions and prompt description.
