---
inventory-delta:
  packages/maistro-design/tests: +14
  packages/hive-conductor/backend/tests: +5
---
# auto-52-design-auth-coverage

CI repair for #2234 (M1-C4 Design Studio/Canvas → Graph/Run):

- `packages/maistro-design/tests` **+14** — canonical execution edge cases
  (admit/execute/fail/replay integrity, capture-empty Attempt rebuild, and
  artifact round-trips) so `canonical_execution.py` / `types.py` clear the
  diff-coverage floor.
- `packages/hive-conductor/backend/tests` **+5** — design service startup
  probes when the core engine / spine stores are absent; EngineService
  `project_scope_store` read-through; supported-path fixture wiring that
  stamps `request.state.principal` so create no longer 401s under postgres CI.
