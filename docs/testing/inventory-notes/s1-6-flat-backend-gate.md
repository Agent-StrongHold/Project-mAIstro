---
inventory-delta:
  tests/: +11
---
# s1-6-flat-backend-gate

Workspace cutover P0.6 (#1046): `scripts/check-cross-package-imports.py` now
rejects a new flat module under `packages/*/backend/`. Eleven new tests in
`tests/test_check_cross_package_imports.py::TestFlatBackendModules`, nothing
removed:

- what counts as flat (a module on `sys.path`, a package-less directory of
  modules) and what does not (packages, data-only dirs, `__pycache__`, modules of
  a backend that is itself a package);
- a new top-level module fails; a new package-less directory fails;
- a new module inside an existing or new package passes;
- a tolerated entry that was deleted, or made into a package, fails as stale, so
  the frozen set can only shrink;
- `main()` passes, reports a new module, and reports a stale entry;
- the real repository passes today and the Conductor backend is actually measured.
