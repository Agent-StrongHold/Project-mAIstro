---
inventory-delta:
  packages/maistro-core/tests: -25
---

# M1 #729 checkpoint-authority test retirement

This change removes the self-only `events/test_checkpoints.py` suite together with the superseded `maistro.events.checkpoints` subsystem. That module contributed 26 collected node IDs: six model/event tests plus ten store-contract tests parametrized across memory and SQLite. One replacement behavioral test pins the surviving canonical recovery boundary against `RunStore` plus graph continuation state, for a net `packages/maistro-core/tests` delta of -25.
