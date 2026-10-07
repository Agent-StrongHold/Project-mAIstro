---
inventory-delta:
  packages/maistro-core/tests: +2
---

# Two container-wiring tests the diff-coverage gate named (#1321)

`Coverage gate (publish-set floor + diff coverage)` failed on exactly two
lines of `_wire_capability_effects`:

```
packages/maistro-core/src/maistro/container.py: 86.7% of 15 changed lines
(need 90%); uncovered 1814, 1837
```

Both additions are in
`packages/maistro-core/tests/capabilities/test_invocation_store.py`; nothing
was removed or renamed.

- **+1** `test_a_supplied_effect_context_is_returned_rather_than_a_second_one_built`
  — covers the early return when an embedder hands the Container an effect
  authority it already built. The test passes a pool *alongside* the supplied
  context, so it asserts the supplied one wins rather than merely that it is
  used. Without that return, the process would hold two Invocation ledgers,
  each believing it is canonical, and the one the caller kept a reference to
  would be the one nothing ever wrote to.

- **+1** `test_configured_bindings_are_registered_in_the_selected_store`
  — covers the loop that puts a deployment's configured Bindings into the
  store just selected. Every egress's `_require_*_binding` reads the
  *registered* record rather than the Binding object it was handed, so a
  configured Binding that never reached the store authorizes nothing: the
  deployment comes up looking configured and refuses every effect. The test
  reads it back through `effects.bindings.get`.
