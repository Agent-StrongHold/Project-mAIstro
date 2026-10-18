---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Capability plugin composition shares the canonical RunStore (#1635)

Adds one regression to `capabilities/test_container_wiring.py`; no tests are
removed or renamed. A deterministic, nonempty `maistro.capabilities` entry
point traverses the real container bootstrap, discovery and registration path.
The same provider is installed inactive, activated, resolved and disabled on
the container's registry. Observed concrete store construction must yield
exactly the container's canonical RunStore.

This covers default in-memory composition with a representative provider. It
does not claim sandboxing or enforcement against arbitrary third-party code,
or durable-backend conformance. No runtime behavior or ownership changes.
