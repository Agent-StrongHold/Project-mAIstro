---
inventory-delta:
  packages/maistro-core/tests: +17
  packages/hive-conductor/backend/tests: +5
---
# HITL timeout and cancellation inventory

Issue #737 adds 17 collected node IDs under `packages/maistro-core/tests` and 5 collected node IDs under `packages/hive-conductor/backend/tests`.

The core count includes 15 new test functions in `test_hitl_settlement.py`, with `test_malformed_durable_deadlines_fail_closed` parametrized across three cases and therefore collecting three node IDs. The Hive count is the five new endpoint/authorization tests in `test_hitl_timeout_cancel.py`.

This note records collection growth only. It does not authorize or baseline any quality, complexity, Vulture, reachability, or acceptance-state debt.
