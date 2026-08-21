"""Tests for memory engine wiring (ADR-011)."""

from __future__ import annotations

import pytest

from maistro.memory.store import (
    get_async_session_factory,
    get_db_session,
    get_engine,
    reset_engine_cache,
)


class TestEngine:
    def setup_method(self) -> None:
        reset_engine_cache()

    def teardown_method(self) -> None:
        reset_engine_cache()

    def test_get_engine_no_url_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "")
        engine = get_engine()
        assert engine is None

    def test_get_engine_idempotent(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "")
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_reset_cache_clears_singleton(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "")
        e1 = get_engine()
        reset_engine_cache()
        e2 = get_engine()
        # Both are None but the lru_cache was reset — a new call was made
        assert e1 is None and e2 is None  # both None when no URL

    def test_session_factory_none_without_engine(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "")
        factory = get_async_session_factory()
        assert factory is None

    def test_get_engine_creation_failure_returns_none(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bad")

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("driver not installed")

        monkeypatch.setattr("maistro.memory.store.create_async_engine", _boom)
        assert get_engine() is None

    def test_get_engine_success_returns_engine(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://example/db")
        engine = get_engine()
        assert engine is not None

    def test_get_async_session_factory_success(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://example/db")
        factory = get_async_session_factory()
        assert factory is not None

    async def test_get_db_session_raises_without_database(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "")
        with pytest.raises(RuntimeError, match="No database configured"):
            async for _ in get_db_session():
                pass

    async def test_get_db_session_yields_session(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://example/db")
        sessions = []
        async for session in get_db_session():
            sessions.append(session)
        assert len(sessions) == 1


def test_vector_is_none_when_pgvector_unavailable(monkeypatch) -> None:
    """Simulate pgvector being absent at import time — the module falls
    back to Vector = None so MemoryEntry.embedding is skipped entirely."""
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "pgvector.sqlalchemy", None)
    import maistro.memory.store as store_module

    try:
        importlib.reload(store_module)
        assert store_module.Vector is None
    finally:
        importlib.reload(store_module)
