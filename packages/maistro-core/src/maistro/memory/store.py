"""SQLAlchemy models and engine factory for PostgreSQL persistence (ADR-011)."""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
except ImportError:
    Vector = None

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_engine() -> AsyncEngine | None:
    """Return an async SQLAlchemy engine, or None if DATABASE_URL is unset."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    try:
        return create_async_engine(url, pool_pre_ping=True)
    except Exception as exc:
        logger.warning("Failed to create database engine: %s", exc)
        return None


@functools.lru_cache(maxsize=1)
def get_async_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Return an async session factory, or None if no engine."""
    engine = get_engine()
    if engine is None:
        return None
    return async_sessionmaker(engine, expire_on_commit=False)


def reset_engine_cache() -> None:
    """Clear the engine/factory caches — for test isolation only."""
    get_engine.cache_clear()
    get_async_session_factory.cache_clear()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    factory = get_async_session_factory()
    if factory is None:
        raise RuntimeError("No database configured")
    async with factory() as session:
        yield session


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    """Persistent task records for durability across restarts."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    # Canonical execution identity (#41). Nullable: rows predating the Run spine
    # and builds with no Run store wired still write a receipt.
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    workspace: Mapped[str] = mapped_column(String(500), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=2)
    phase: Mapped[str | None] = mapped_column(String(20))
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    constraints: Mapped[list[Any] | None] = mapped_column(JSONB)
    branch: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryEntry(Base):
    """Vector-searchable memory entries for codebase knowledge."""

    __tablename__ = "memory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Vector embedding — 1536 dims (OpenAI ada-002 compatible)
    # Will be None if pgvector is not installed
    if Vector is not None:
        embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))


class KnowledgeNode(Base):
    """Knowledge graph nodes for module/function dependency tracking."""

    __tablename__ = "knowledge_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)  # module, function, class
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    depends_on: Mapped[list[Any] | None] = mapped_column(JSONB)  # list of node names
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_knowledge_workspace_type", "workspace", "node_type"),)
