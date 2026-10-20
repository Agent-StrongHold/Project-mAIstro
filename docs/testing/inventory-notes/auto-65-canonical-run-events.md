---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# #65 canonical Run event inspection

Adds a Goal-associated Run detail regression proving inspection reads canonical
EventStore records, filters out events for other Run IDs in the same Workspace
stream, and preserves the canonical Run identifier. It also reconnects using
canonical Run identity after the product-local Run projection is unavailable,
proving that the event replay does not depend on that projection. This closes
the prior canonical-only detail gap when the core Container exposes its event
store.

Validation: `uv run pytest packages/hive-conductor/backend/tests/test_goal_inspection.py -x -q`
(34 passed); `uv run ruff check packages/hive-conductor/backend/tests/test_goal_inspection.py`
and `uv run ruff format --check packages/hive-conductor/backend/tests/test_goal_inspection.py`.
