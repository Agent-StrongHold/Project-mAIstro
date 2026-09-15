---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/maistro-server/tests: +3
  packages/hive-conductor/backend/tests: +1
---

# #1057 — task principal delegation

Adds contract coverage for the signed Conductor-to-maistro-server delegation envelope,
server-side effective actor binding and two-principal task isolation. The adapter tests
cover propagation of signed user context and fail-closed configuration; the existing
production task bridge tests are updated to provide the required host key.
