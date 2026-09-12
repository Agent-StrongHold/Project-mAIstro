---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +2
  packages/hive-conductor/backend/tests: +2
---
# #1165 review: the fail-closed table reaches the production paths

- `test_container_security_wiring.py` (+3): a turn routed without an
  identity reaches the conduit as the role-less `ANONYMOUS_AUTH` rather than
  `None`, and that principal is denied by the empty table and by a configured
  preset alike (parametrized over both).
- `config/test_inert_security_knobs.py` (+3): the YAML `security` section now
  carries `permission_preset` / `permissions` (defaults, accepted values,
  unknown preset refused at load).
- `maistro-server/tests/test_agent_config_security.py` (+2, new file):
  `_agent_config` copies the YAML grants onto `AgentConfig.security`, and a
  server without a YAML file gets the empty fail-closed table.
- `hive-conductor/tests/test_maistro_core_adapter.py` (+2): the bridge copies
  `MAISTRO_PERMISSION_PRESET` / `MAISTRO_PERMISSIONS` onto the Container's
  config, and `route(auth=...)` passes the caller's principal through.
