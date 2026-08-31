---
inventory-delta:
  tests/: +15
---
# claude-issue-188-memory-entries-embedding-is-text-830a

One new file, no removals and no renames, so the whole delta is additions
(#188).

`tests/migrations/test_memory_entries_embedding_type.py` is +15: twelve cases
that need a real pgvector server (the column's actual catalog type, the
preservation of unconvertible values across the repair, scoped similarity and
its query plan, and the index shape) and three that read the tree instead of a
database.

The twelve skip without `MAISTRO_TEST_DATABASE_URL`, so a laptop run collects
15 and skips 12. They need a server on purpose: the defect is that a column
named `embedding` was `text` while three artefacts said `vector(1536)`, and a
double cannot disagree with itself. `MAISTRO_REQUIRE_PG_LEGS` turns the skip
into a failure where CI guarantees a server.

The three that need no server assert that nothing in the tree still describes
the column wrongly. Both were mutation-verified against the pre-repair text:
restoring `001`'s "managed by pgvector" comment fails one, and restoring
`vectors.py`'s citation of the non-existent `007_memory_embedding_columns.py`
fails the other. The first draft of that second test passed under the mutation
— it filtered tokens on a leading digit while the citation is written
`alembic/versions/011_....py` — and was rewritten to match by basename.

No existing test was deleted, relaxed or renamed.
