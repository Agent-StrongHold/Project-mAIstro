---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---

# #1187 authenticated session idle policy

Ten backend cases cover the governed seven-day absolute and 30-minute idle
policy, exact boundary expiry, clock rollback, observational `whoami` behavior,
eligible authenticated activity, rejected HTTP polling and WebSocket handshakes,
absolute-cap enforcement after refresh, deactivation/reactivation invalidation,
and explicit revocation.
The UI policy metadata is asserted without exposing the opaque session id.
