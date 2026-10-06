---
inventory-delta:
  packages/maistro-core/tests: +1
---

# #961 adapter-scoped request-alias ceiling repair

Adds `test_request_alias_cannot_bypass_an_adapter_scoped_binding` in
`packages/maistro-core/tests/capabilities/test_provider_adapters.py`.

The regression registers Acme and a rival adapter, then supplies the rival
model as the request alias to an unpinned Acme-scoped Binding. Resolution must
return canonical `Unavailable`, rather than resolving the rival provider. It
also proves that an alias for Acme's own declared model remains selectable.
