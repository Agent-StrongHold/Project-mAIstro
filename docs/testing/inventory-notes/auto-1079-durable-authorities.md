---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-1079 durable authorities

Adds one production-composition test proving SQLite-backed Binding and
Invocation authorities are selected by `create_container` and configured model
Bindings remain resolvable after a Container restart.
