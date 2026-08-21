import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://mcp:mcp@localhost:5441/mcp_orders",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def create_all():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
