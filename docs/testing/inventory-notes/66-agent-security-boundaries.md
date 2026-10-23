---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +2
---
# #66 Agent security boundaries

The Agent now owns the invariant content-security pipeline at the product
boundary: it scans the normalized aggregate after session-history injection,
so cross-turn instruction fragments cannot bypass Warden, and it applies the
canonical Sentinel output boundary to final model text. Missing auth is
represented by the role-less anonymous principal rather than bypassing the
protected path. The core tests cover aggregate scanning and final-output sanitization/auth
propagation. The server's roster-floor fallback now uses the same boundaries,
and its two tests prove normalized inbound aggregation and anonymous final
output authorization.
