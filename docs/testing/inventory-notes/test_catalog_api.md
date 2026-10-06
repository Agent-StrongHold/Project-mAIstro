---
inventory-delta:
  packages/maistro-server/tests: +9
---
Private organizational extension catalog API tests (#979, M9-J1).

`packages/maistro-server/tests/api/test_catalog_api.py` replaces its
syntactically broken draft with nine cases over the `/catalog` router,
with auth dependency overrides following the `test_extensions_api.py`
pattern:

- discovery from a fresh client: the list view returns every published
  candidate with publisher, digest (package/manifest), requested-permission
  and entry-point metadata — inspection before any download;
- deterministic ordering: name-then-version, not snapshot order;
- search/filter: case-insensitive search across extension name and
  publisher, exact publisher filtering, the combined filter, and empty
  results for no match and for an organization with no catalog;
- version history: newest first with per-version manifest detail, and an
  empty list for unknown extensions;
- version detail: the immutable-artifact digest chain per version, with 404
  for unknown versions and unknown extensions;
- authentication: with real auth and configured API keys, a credentialless
  caller and a wrong credential both fail closed with 401 on every route's
  shared dependency, and an app with no wired catalog service answers 503
  instead of improvising;
- public-surface declaration: every `@router` handler in `catalog.py` must
  appear in the module's `__all__`, keeping the fastapi-route-handler
  Vulture ledger clean (the same drift test the extensions and canvas
  routers carry).

No existing cases were removed or renamed; the suite count moves +9.
