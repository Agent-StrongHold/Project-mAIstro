---
inventory-delta:
  packages/maistro-core/tests/events: +3
  packages/maistro-core/tests/capabilities: +1
  packages/hive-conductor/backend/tests: +6
---
# auto-1171 — canonical Warden composition at Conductor and event re-entry boundaries

Added regression coverage for the issue's security boundaries:

- event conductor actions scan the exact labelled model message with the
  `tool_result` boundary, refuse blocked previews before HTTP, and refuse when
  the canonical Warden is unavailable;
- the Conductor agent scan reads the application Container Warden and returns a
  503 when that composition is absent;
- the harness manager reads the application Container Warden and its route
  returns a 503 when the composition is absent.
