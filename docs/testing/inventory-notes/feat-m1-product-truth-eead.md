---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# Mission detail must not name an agent the Run does not have

`packages/hive-conductor/backend/tests`: +3. The API regression
`test_mission_detail_does_not_show_an_agent_the_run_does_not_have` asserts
that planted `assigned_agents` / step `agent_id` values are omitted from
list, detail, steps, and status without modifying stored attribution, and
that create does not store a client-supplied agent or owner. It also pins
the authenticated create/status audit actor.

Two parametrized cases of
`test_mission_agent_sanitization_keeps_other_users_records_private` prove
that response sanitization retains ownership checks in both the stub and
engine-to-store fallback paths. The existing engine-create test also submits
a forged agent and checks the unchanged user/Run projection. No existing
node IDs moved or were removed.
