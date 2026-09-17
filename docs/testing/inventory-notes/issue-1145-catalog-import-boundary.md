---
inventory-delta:
  packages/maistro-design/tests: +21
---
# Issue #1145 catalog import boundary

Eleven importer tests add twenty-one collected node IDs (the path spelling and
non-string cases are parameterized) covering lowercase kebab-case slug
validation, POSIX/Windows path spellings, encoded and Unicode-normalized
traversal forms, relative traversal with an external matching payload, missing
and invalid catalog roots, catalog-root, directory, and payload-file symlink
escapes, payload and directory swaps staged after validation (the TOCTOU
window; reads run through retained no-follow descriptors, so a swapped symlink
is rejected as a policy error instead of followed), and a valid flat catalog
fixture retaining manifest and token imports.
The shipped Open Design catalog is flat, so nested path slugs are rejected as
path syntax rather than treated as a supported layout.
