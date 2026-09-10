---
inventory-delta:
  tests/: +2
---
# fix-m1-1142-reachability-loose-src-files-f9b5

Two new tests in `tests/test_reachability_source_universe.py` for #1142:

- A loose file directly under a `packages/*/src` root is discovered as its
  own module (the fixture shape #1142 asks for).
- An unbaselined loose src-root file fails as newly unreachable, proving the
  fix doesn't just discover the module but fails closed on it too.

No tests removed or renamed.
