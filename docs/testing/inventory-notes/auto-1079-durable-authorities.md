---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-1079 durable authorities

Adds production-composition tests proving SQLite-backed Binding and Invocation
authorities are selected by `create_container`, configured model Bindings remain
resolvable after a Container restart, and Container provider health refuses a
physical dispatch before an Invocation is created.
