---
inventory-delta:
  packages/maistro-design/tests: +15
---
# Issue #1145 catalog import boundary

Six importer tests add fifteen collected node IDs (the path spelling case is
parameterized) covering lowercase kebab-case slug validation,
POSIX/Windows path spellings, encoded and Unicode-normalized traversal forms,
relative traversal with an external matching payload, catalog-root, directory,
and payload-file symlink escapes, and a valid flat catalog fixture retaining
manifest and token imports. The shipped Open Design catalog is flat, so nested
path slugs are rejected as path syntax rather than treated as a supported layout.
