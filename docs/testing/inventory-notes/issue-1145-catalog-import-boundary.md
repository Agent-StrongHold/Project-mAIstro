---
inventory-delta:
  packages/maistro-design/tests: +19
---
# Issue #1145 catalog import boundary

Nine importer tests add nineteen collected node IDs (the path spelling and
non-string cases are parameterized) covering lowercase kebab-case slug
validation, POSIX/Windows path spellings, encoded and Unicode-normalized
traversal forms, relative traversal with an external matching payload, missing
and invalid catalog roots, catalog-root, directory, and payload-file symlink
escapes, and a valid flat catalog fixture retaining manifest and token imports.
The shipped Open Design catalog is flat, so nested path slugs are rejected as
path syntax rather than treated as a supported layout.
