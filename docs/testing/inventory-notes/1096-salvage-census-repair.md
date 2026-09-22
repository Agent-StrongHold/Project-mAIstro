---
inventory-delta:
  tests/: +6
---

# 1096-salvage-census-repair

Salvage repair for #1096. Five of the six `tests/` node IDs came in with the
develop merge (b533e2abf) that completed the interrupted prior-salvage merge;
their authors' own notes live on develop. The sixth is
`tests/test_check_security_inventory.py::test_the_census_sees_function_local_httpx_imports`,
the regression test for the census scanner gap the prior run left open: a
module-level-only alias scan reported no finding for
`def make(): from httpx import Client; return Client()`, so the completion gate
could be dodged by moving an import inside a function. `_httpx_aliases` now
walks the whole tree, and the test proves both the constructor census and the
sibling call census see function-local imports.
