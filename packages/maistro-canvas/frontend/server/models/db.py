"""Engine and session factory, built from the one configured URL (#432).

The engine is built on first use rather than at import. `DATABASE_URL` is
required now, and a module that raises the moment anything imports it makes the
whole package unimportable without a database -- including the model tests,
which never touch one.
"""

from collections.abc import AsyncIterator

from server.config import require_database_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

_engine: AsyncEngine | None = None
_async_session: sessionmaker | None = None


def get_engine() -> AsyncEngine:
    """The process-wide engine, built on first call."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            require_database_url(), echo=False, pool_size=5, max_overflow=10
        )
    return _engine


def get_async_session() -> sessionmaker:
    """The session factory bound to `get_engine()`."""
    global _async_session
    if _async_session is None:
        _async_session = sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _async_session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_async_session()() as session:
        yield session


async def create_all() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
