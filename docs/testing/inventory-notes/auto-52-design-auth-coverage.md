---
inventory-delta:
  packages/maistro-design/tests: +13
  packages/hive-conductor/backend/tests: +4
---
# auto-52-design-auth-coverage

CI repair for #2234 (M1-C4 Design Studio/Canvas → Graph/Run):

- `packages/maistro-design/tests` **+13** — canonical execution edge cases
  (admit/execute/fail/replay integrity and artifact round-trips).
- `packages/hive-conductor/backend/tests` **+4** — design service startup
  probes when the core engine / spine stores are absent, plus supported-path
  fixture wiring that stamps `request.state.principal` so create no longer
  401s under postgres CI.
