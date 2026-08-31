"""`memory_entries.embedding` becomes the vector(1536) it always claimed to be (#188).

Migration 001 creates the column twice and the first spelling wins:

    sa.Column("embedding", sa.Text, nullable=True),  # vector(1536) — managed by pgvector
    ...
    op.execute("ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS embedding vector(1536)")

`create_table` makes it `text`. The `ALTER` is guarded by `IF NOT EXISTS`, a
column of that name exists by then, so PostgreSQL skips it -- no error, no
notice. The column has been `text` in every deployment since, while the ORM
model declares `Vector(1536)` and `memory/vectors.py` documents the width as a
schema fact. 011 does the same job correctly for `learnings`, which is why that
one is right and this one is not.

Forward repair rather than an edit to 001: 001 has run everywhere, and a
migration is a record of what happened, not a description of what should have.

**Unconvertible values are preserved, not discarded.** A text column can hold
anything, and this one is reachable by hand even if nothing in the repository
writes it. Values that parse at the declared width are cast; the rest move to
`embedding_unconvertible` so the upgrade neither aborts on a malformed row nor
throws data away. An upgrade that dies partway leaves an operator with a
half-migrated database and no forward path that is not hand-editing rows.

The width is 1536 and this revision does not reopen it (ADR-082326-8194 is
Accepted). Repairing a column to the width every other artefact already claims
is not the moment to change that number -- and doing both at once would make it
impossible to tell later which change broke something.

Revision ID: 029
Revises: 028
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None

_TABLE = "memory_entries"
_INDEX = "ix_memory_entries_embedding_hnsw"

#: The one width the memory schema stores, mirroring 011's `_DIMENSIONS` and
#: `maistro.memory.vectors.EMBEDDING_DIMENSIONS`. A test holds the three equal.
_DIMENSIONS = 1536

#: Move every value the target type cannot accept out of the way, one row at a
#: time, inside a savepoint that catches the cast failure.
#:
#: A set-based predicate would be faster and is not available: pgvector 0.8.6's
#: input function does not implement PostgreSQL's soft-error protocol, so
#: `pg_input_is_valid(embedding, 'vector')` *raises* instead of returning false
#: (verified against pgvector 0.8.6 on PostgreSQL 18). Nor does `AND`
#: short-circuit in SQL: guarding `vector_dims(embedding::vector)` behind a
#: validity test in the same `WHERE` still lets the planner evaluate the cast
#: first, which is exactly how the first draft of this migration died on a row
#: containing `banana`.
#:
#: `BEGIN ... EXCEPTION` establishes a subtransaction per row, which is the one
#: construct that reliably contains a cast failure. Row-at-a-time is acceptable
#: here for a specific reason rather than by default: nothing in this repository
#: writes `memory_entries.embedding`, so this loop sees zero rows in every
#: deployment we can observe, and the deployments we cannot observe are exactly
#: the ones that must not lose data to a faster statement.
_QUARANTINE = f"""
DO $$
DECLARE
    row_id integer;
    parsed vector({_DIMENSIONS});
BEGIN
    FOR row_id IN SELECT id FROM {_TABLE} WHERE embedding IS NOT NULL LOOP
        BEGIN
            SELECT embedding::vector({_DIMENSIONS}) INTO parsed
              FROM {_TABLE} WHERE id = row_id;
        EXCEPTION WHEN others THEN
            -- Both failure modes land here: malformed text, and a well-formed
            -- vector of the wrong width. The row keeps its value under a name
            -- that says it could not be read, rather than being dropped or
            -- aborting the upgrade for every other row.
            UPDATE {_TABLE}
               SET embedding_unconvertible = embedding, embedding = NULL
             WHERE id = row_id;
        END;
    END LOOP;
END $$;
"""


def upgrade() -> None:
    # The extension first, exactly as 011 does. `memory_entries` predates 011
    # in the ladder but this revision does not: on a database migrated in order
    # the extension is already there, and on one repaired out of order it is
    # not, so this asks rather than assumes.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    current = columns.get("embedding")
    # Idempotent, and deliberately: a database repaired by hand before this
    # revision ran is a database whose operator did the right thing, and
    # rewriting the table again would take an ACCESS EXCLUSIVE lock to change
    # nothing.
    if current is not None and not isinstance(current["type"], sa.Text().__class__):
        return

    op.add_column(_TABLE, sa.Column("embedding_unconvertible", sa.Text, nullable=True))
    # Quarantine before the cast, because after the cast the original text is
    # gone and there is nothing left to preserve.
    op.execute(_QUARANTINE)
    # Every surviving value is now one this cast accepts, so `USING` cannot
    # meet a row it would fail on.
    op.execute(
        f"ALTER TABLE {_TABLE} ALTER COLUMN embedding "
        f"TYPE vector({_DIMENSIONS}) USING embedding::vector({_DIMENSIONS})"
    )
    # `vector_cosine_ops`, not L2, and the same name shape 011 uses: the
    # engine's similarity is cosine, and a second index strategy for the same
    # access pattern in the same database is the per-table lookup
    # ADR-082326-8194 argued against.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE} USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Back to `text`, restoring what was quarantined.

    Lossless in the direction that matters: a vector cast back to text is the
    same literal pgvector would have accepted, and the quarantined originals go
    back to the column they came from. What a round trip does not restore is
    whitespace and float formatting inside a value that was already valid --
    `'[1.0, 2.0]'` returns as `'[1,2]'` -- which is a rendering difference, not
    a data loss.
    """
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN embedding TYPE text USING embedding::text")
    op.execute(
        f"UPDATE {_TABLE} SET embedding = embedding_unconvertible "
        f"WHERE embedding_unconvertible IS NOT NULL"
    )
    op.drop_column(_TABLE, "embedding_unconvertible")
