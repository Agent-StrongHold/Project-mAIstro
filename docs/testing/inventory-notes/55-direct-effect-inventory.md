---
inventory-delta:
  tests/: +10
---

# #55 direct-effect inventory analyzer coverage

Adds ten focused root-suite cases for the AST direct-effect analyzer: positive model and typed-tool detection, import-vs-usage behavior, stable identities, bidirectional inventory reconciliation, and the SQL/unrelated-HTTP/`maistro.events.invocations.InvocationStore` false-positive cases called out by #55.
