---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-server/tests/api: +3
---
# Issue #234 production Workspace scope

Five behavioral regression tests cover the production Workspace-scope boundary.

Hive contributes two tests proving that `MaistroServerTaskBackend` sends the
shared Workspace admission header only for explicitly scoped submissions and
preserves the existing unscoped/default behavior.

maistro-server contributes three tests against the SQLite canonical execution
spine: a named Workspace resolves to that Workspace's Root Project, two named
Workspaces resolve to distinct Projects, and a blank explicit scope is rejected
before admission.

No existing test node IDs moved or were removed.
