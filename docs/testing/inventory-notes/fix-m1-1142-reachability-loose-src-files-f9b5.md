---
inventory-delta:
  tests/: +4
---
# fix-m1-1142-reachability-loose-src-files-f9b5

Two new tests in `tests/test_reachability_source_universe.py` for #1142:

- A loose file directly under a `packages/*/src` root is discovered as its
  own module (the fixture shape #1142 asks for).
- An unbaselined loose src-root file fails as newly unreachable, proving the
  fix doesn't just discover the module but fails closed on it too.

Two more, added closing a gap a PR review surfaced: a loose module's key is
its bare stem, unscoped by src root, so a second root claiming the same
identity (another loose file, or a package directory's own bare name) would
silently overwrite the first module in `_collect_modules`' dict -- reopening
the exact invisible-module blind spot #1142 exists to close, for same-named
loose modules specifically. `_validate_no_duplicate_loose_modules` now fails
closed on both collision shapes.

No tests removed or renamed.
