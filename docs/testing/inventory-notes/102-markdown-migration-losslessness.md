---
inventory-delta:
  packages/maistro-core/tests: +23
---

# Markdown migration losslessness (#102)

`packages/maistro-core/tests/backlog/test_markdown_migration.py` is new: 23
node IDs proving the DB import of root `BACKLOG.md` preserves everything the
cutover acceptance names. The real file round-trips byte-for-byte through
parse → structured items → render (23 of the cases cover the real file and
the dependency grammar); the three written blocked-by forms parse (canonical
bullet, bare sibling numbers `010/011/012`, header-suffix `Depends on`),
prose mentions do not invent dependencies, unknown refs and cycles are
refused, the eight status-legend words map onto structured open/closed state,
duplicate ids are refused, and `import_document` is idempotent (no version
churn, no fabricated history) while re-importing changed items updates state
and closes/reopens with recorded events. No existing test was removed or
renamed.
