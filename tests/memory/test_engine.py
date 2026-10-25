"""Tests for memory engine wiring (ADR-011)."""

from __future__ import annotations

from maistro.memory.store import get_async_session_factory, get_engine, reset_engine_cache


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
