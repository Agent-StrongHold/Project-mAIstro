---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Mission detail must not name an agent the Run does not have

`packages/hive-conductor/backend/tests`: +1. One API test,
`test_mission_detail_does_not_show_an_agent_the_run_does_not_have`, asserts
that a planted `assigned_agents` / step `agent_id` is omitted from list,
detail, steps, and status, and that create does not store a client-supplied
agent. No existing node IDs moved or were removed.
