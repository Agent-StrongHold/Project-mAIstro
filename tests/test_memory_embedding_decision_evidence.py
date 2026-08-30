"""Acceptance evidence for ADR-082326-8194 / #188.

The PostgreSQL migration suite remains the behavioral proof against a real
pgvector database. These contract tests make the accepted decision visible to
the repository acceptance ladder on every root test run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore
from maistro.memory.vectors import EMBEDDING_DIMENSIONS, require_matching_dimension
from maistro.persistence.pg_learnings import similarity_query
from maistro.types.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "011_memory_embedding_columns.py"


@pytest.mark.ac("ADR-082326-8194/AC-1")
def test_memory_embedding_width_is_one_declared_schema_fact() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert EMBEDDING_DIMENSIONS == 1536
    assert "_DIMENSIONS = 1536" in migration
    assert "embedding vector({_DIMENSIONS})" in migration


@pytest.mark.ac("ADR-082326-8194/AC-2")
def test_embedding_client_width_mismatch_fails_before_writes() -> None:
    class NarrowClient:
        dimension = 384

    with pytest.raises(ConfigError) as excinfo:
        require_matching_dimension(NarrowClient())  # type: ignore[arg-type]

    message = str(excinfo.value)
    assert "384" in message
    assert str(EMBEDDING_DIMENSIONS) in message


@pytest.mark.ac("ADR-082326-8194/AC-3")
def test_scope_and_cosine_similarity_share_the_postgres_query() -> None:
    org_query = similarity_query(scoped_to_agent=False)
    agent_query = similarity_query(scoped_to_agent=True)

    for query in (org_query, agent_query):
        assert "org_id = $2" in query
        assert "embedding IS NOT NULL" in query
        assert "ORDER BY embedding <=> $1::vector" in query
    assert "agent_id = $3" in agent_query


@pytest.mark.ac("ADR-082326-8194/AC-4")
@pytest.mark.asyncio
async def test_durable_hybrid_store_writes_and_reads_row_vectors() -> None:
    class Embeddings:
        dimension = EMBEDDING_DIMENSIONS

        async def embed(self, text: str) -> list[float]:
            return [float(len(text))] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    class Store:
        def __init__(self) -> None:
            self.embedding_written = False
            self.similarity_read = False

        async def store(self, learning: object) -> int:
            return 7

        async def text_of(self, learning_id: int) -> str:
            assert learning_id == 7
            return "persisted learning"

        async def set_embedding(self, learning_id: int, vector: list[float]) -> None:
            assert learning_id == 7
            assert len(vector) == EMBEDDING_DIMENSIONS
            self.embedding_written = True

        async def find_similar(self, vector: list[float], **kwargs: object) -> list[object]:
            assert len(vector) == EMBEDDING_DIMENSIONS
            assert kwargs["org_id"] == "workspace-a"
            self.similarity_read = True
            return []

        async def find_relevant(self, *args: object, **kwargs: object) -> list[object]:
            return []

    store = Store()
    hybrid = DurableHybridLearningStore(store, Embeddings())  # type: ignore[arg-type]

    assert await hybrid.store(object()) == 7  # type: ignore[arg-type]
    await hybrid.find_relevant("query", org_id="workspace-a")

    assert store.embedding_written
    assert store.similarity_read
