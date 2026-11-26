---
inventory-delta:
  packages/maistro-core/tests: +3
---
Container wiring tests for the private organizational extension catalog
(#979, M9-J1 coverage-gate repair).

`packages/maistro-core/tests/extensions/test_container_wiring.py` gains
`TestCatalogContainerWiring`, three cases pinning the `Container.
ensure_catalog_service` contract that the `/catalog` API routes depend on:

- lazy build and per-container caching: the service is `None` until first
  ensured, and every later call returns the same instance;
- default wiring: the lazily built service runs over the in-memory catalog
  store, and that store is cached back onto the container so callers
  bypassing the service see the same snapshot the API serves;
- pre-wired store kept: a container configured with a catalog store has the
  service built over exactly that store, not a fresh one.

The first coverage run of the branch left `ensure_catalog_service`'s body
uncovered (CI diff-coverage gate: `container.py 33.3% of 9 changed lines`),
because the API tests stub the container with a `SimpleNamespace` and no
core test exercised the real method. These cases close that gap and also
exercise both branch arcs (service already built / not yet built, store
pre-wired / default).

No existing cases were removed or renamed; the suite count moves +3.
