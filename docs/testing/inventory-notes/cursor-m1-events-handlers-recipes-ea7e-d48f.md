---
inventory-delta:
  packages/maistro-core/tests: +4
---
# cursor-m1-events-handlers-recipes-ea7e-d48f

Four tests cover the new process subscription surface from #2313:
`wire_legacy_trigger_surface` registers every builtin action handler plus the
recipe catalog disabled (test_wiring), `install_builtin_handlers` subscribes
each `BUILTIN_HANDLERS` action type (test_handlers), and
`install_builtin_recipes` lands the catalog disabled by default with an
explicit opt-in to arm it (test_recipes). No tests were removed or renamed.
