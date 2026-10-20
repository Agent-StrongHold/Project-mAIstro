---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# #65 canonical Run event inspection

Adds a Goal-associated Run detail regression proving inspection reads canonical
EventStore records, filters out events for other Run IDs in the same Workspace
stream, and preserves the canonical Run identifier. This closes the prior
canonical-only detail gap when the core Container exposes its event store.

Validation: `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -x -q`
(34 passed). Ruff validation is rerun after import formatting.
