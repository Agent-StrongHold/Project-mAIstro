---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# auto-65 canonical Goal inspection

Adds a regression that admits a Run with the canonical `goal_id` and
`goal_revision` fields, then changes the canonical Goal separately. The
inspection projection must show the Goal reader's explicit state while keeping
the Run-bound revision's desired/success/stop conditions; Run completion must
not decide the Goal.
