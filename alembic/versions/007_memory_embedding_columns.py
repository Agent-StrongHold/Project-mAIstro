"""Embedding vectors on the memory rows, at one declared dimension.

Revision ID: 007_memory_embeddings
Revises: 006_outcome_scope_feedback
Create Date: 2026-08-23

`ADR-082226-5104` chose pgvector as the vector store and migration 001 carried
that out for `memory_entries` alone. `learnings`, `outcomes` and
`episodic_memories` -- the tables `maistro.memory` actually reads and writes --
had no embedding column, so similarity could not compose with scope in one
query. Scope, provenance, recency and status all live on the row; putting the
vector anywhere else turns a scoped similarity read into fetch-then-filter in
Python, which is slower and makes the scope filter something other than the
database's job.

Dimension and index are `ADR-082326-8194`'s decisions, not this file's:
`vector(1536)` to match the width `memory_entries` already stores, and HNSW
because IVFFlat trained by a migration against an empty table is degenerate --
it needs populated data to build its lists.

Shape follows 001: extension first, then `ALTER TABLE … ADD COLUMN IF NOT
EXISTS … vector(N)` rather than a typed column in `create_table`, because
SQLAlchemy has no native `vector` type without the pgvector dialect package and
this project does not depend on it.
"""

from __future__ import annotations

from alembic import op

revision = "007_memory_embeddings"
down_revision = "006_outcome_scope_feedback"
branch_labels = None
depends_on = None

#: Tables gaining a vector, with the scope columns their similarity reads filter
#: on. The scope columns are not indexed *with* the vector: pgvector's HNSW is a
#: single-column index, so a composite is not available, and the planner is left
#: to combine the vector index with the existing scope indexes 001 created.
_EMBEDDED_TABLES = ("learnings", "outcomes", "episodic_memories")

#: `ADR-082326-8194`. Kept as a literal rather than imported from
#: `maistro.memory` -- a migration must describe the schema at its own revision,
#: and importing a constant that a later release may change would make this file
#: mean something different depending on when it runs.
_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table in _EMBEDDED_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS embedding vector({_DIMENSIONS})")
        # `vector_cosine_ops`, not L2: the engine's similarity is cosine
        # (`memory/learnings/embeddings.py::cosine_similarity`), and an index
        # built for a different distance function is silently unused by a
        # cosine-ordered query -- the read still works, and still scans.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_embedding_hnsw "
            f"ON {table} USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    for table in _EMBEDDED_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_hnsw")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding")
    # The extension is left alone: `memory_entries.embedding` from 001 still
    # needs it, and dropping it here would break a downgrade to any revision
    # above 001.
