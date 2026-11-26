---
inventory-delta:
  packages/maistro-core/tests: +3
---
# cursor-m1-graph-waves-connect-ea7e-ada0

CONNECT coverage for durable traversal helpers on #2314 / PR #2329.

Adds three tests in `test_traversal_helpers_connect.py` that exercise
`_drain_steering_queue` and `_prepare_traversal_blackboard` directly:

- string entries move from `_steering_queue` onto `_steering` while
  non-strings and empties are dropped and `shared_context` is preserved;
- empty or non-list queues are a no-op (queue key still popped);
- prepare hydrates the blackboard, drains steering, and keeps creative
  `shared_context` dicts intact.

These close the diff-coverage gap on the new drain helper (lines that CI
reported uncovered at 70.8% of changed lines in `executor.py`). The empty-
board `should_compact` probe on the prepare path stays so vulture keeps
`ContextCompactor.should_compact` marked used without auto-compacting live
snapshots (which would wipe `shared_context` via `_simple_compact`).
