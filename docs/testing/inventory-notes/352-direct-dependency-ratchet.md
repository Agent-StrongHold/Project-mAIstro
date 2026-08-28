---
inventory-delta:
  tests/: +9
---

# #352 direct runtime dependency usage coverage

Adds nine focused root-suite cases for the production direct-dependency ratchet: requirement normalization, static and literal-dynamic imports, test-only false positives, distribution-to-import mapping, missing exception failure, reviewed non-import runtime exceptions, stale exceptions after direct use or dependency removal, and required category/owner/rationale metadata.

The gate covers `[project].dependencies` for every `packages/*/pyproject.toml`; optional/dev groups are intentionally outside this production-runtime check. Production Python under each package is scanned with AST imports while test, mutant, build, distribution, and virtual-environment trees are excluded.
