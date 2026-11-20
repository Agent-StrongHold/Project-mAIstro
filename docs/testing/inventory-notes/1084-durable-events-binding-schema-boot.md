---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 1084 durable-events binding schema boot

One PostgreSQL-leg test in the durable-events Container wiring suite pins the
#1084 CI-repair fix: wiring a Container against a database with the capability
Binding tables dropped must still come up, because the boot model.chat Binding
registration `put`s into `PgBindingStore` and that `put` reads the revocation
tombstone (#1133) first. `_select_effect_backend` therefore has to
`ensure_schema()` the Binding store exactly as it already did for the event,
audit and Goal stores. The test asserts the store type, that the boot
model.chat Binding row landed in the table `ensure_schema` created, and that
`capability_binding_revocations` exists — the table whose absence killed
Container startup in the durable-events CI leg.
