---
inventory-delta:
  packages/maistro-rsi/tests: +7
---

# Promotion export path boundaries

Seven cases cover separator/empty stems (four), an existing out-of-root
symlink, legitimate symlinked export roots plus retry idempotence, and a leaf
symlink planted at open time. The first five rejection cases fail on base
cc6e4899; the traversal case actually writes outside the export directory.
The focused promotion export/review/path-split suites pass (42 tests).
