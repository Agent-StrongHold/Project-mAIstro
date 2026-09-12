---
inventory-delta:
  tests/: +8
---
# fix-m1-1144-shipped-surface-discovery

Added regression coverage for issue #1144:

- multi-statement and control-flow fake-success returns, including `log(...); return {"status": "ok"}`;
- statically assembled decorator paths/methods and `add_api_route` registration;
- unresolved dynamic decorators and registrations requiring an explicit matrix entry;
- common frontend client/request wrapper mutations.

No tests removed or renamed.
