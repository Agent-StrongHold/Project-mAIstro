"""The embedding width the memory schema is built for, and the check that a
configured client agrees with it (ADR-082326-8194).

`EmbeddingClient.dimension` is a property of whatever client is configured,
resolved at runtime. A `vector(N)` column is fixed when the migration runs.
Nothing reconciled the two, so a deployment could configure a 384-dimension
client against a 1536-dimension column and find out at the first `INSERT` --
by which time the failure is a write error in a background path, far from the
configuration that caused it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.types.errors import ConfigError

if TYPE_CHECKING:
    from maistro.protocols.embeddings import EmbeddingClient

#: The width every `embedding vector(N)` column in the memory schema is created
#: at, by `alembic/versions/011_memory_embedding_columns.py` for `learnings` and
#: by `029_memory_entries_embedding_is_a_vector.py` for `memory_entries`.
#:
#: Not 001. That revision named the width in a comment and produced a `text`
#: column -- its `ADD COLUMN IF NOT EXISTS ... vector(1536)` was a no-op against
#: the column its own `create_table` had just made. 029 is the repair (#188,
#: ADR-083026-4b70).
#:
#: 1536 is OpenAI's `ada-002` / `3-small` width. `ADR-082326-8194` matched it
#: deliberately rather than right-sizing: a second width in one database means
#: two index strategies, two client configurations and a per-table lookup at
#: every call site. Read that ADR before changing this number -- it is not a
#: constant so much as a schema fact, and moving it rewrites every stored
#: vector across four tables.
EMBEDDING_DIMENSIONS = 1536


def require_matching_dimension(client: EmbeddingClient) -> None:
    """Refuse an embedding client whose width the schema cannot store.

    Raises `ConfigError` naming both numbers. Deliberately not a truncate or a
    pad: a 1536-column fed 384 real dimensions and 1152 zeros returns rankings
    that look plausible and are meaningless, which is worse than a refusal
    because nothing surfaces it.
    """
    dimension = client.dimension
    if dimension != EMBEDDING_DIMENSIONS:
        msg = (
            f"embedding client returns {dimension}-dimension vectors, but the memory "
            f"schema stores vector({EMBEDDING_DIMENSIONS}) (ADR-082326-8194). Configure a "
            f"client at {EMBEDDING_DIMENSIONS} dimensions, or migrate the columns -- which "
            f"rewrites every stored vector."
        )
        raise ConfigError(msg)


def to_pgvector_literal(vector: list[float]) -> str:
    """Render a vector for a `$n::vector` parameter.

    asyncpg has no codec for pgvector's type, and this project does not depend
    on the `pgvector` package, so the value crosses as text and is cast in SQL.
    Passing the Python list directly raises; passing `str(vector)` happens to
    work only because Python's list repr and pgvector's input format agree on
    brackets and commas, which is not a contract worth relying on unstated.
    """
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


__all__ = ["EMBEDDING_DIMENSIONS", "require_matching_dimension", "to_pgvector_literal"]
