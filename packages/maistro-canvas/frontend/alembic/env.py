import asyncio
import os
import sys

from alembic import context
from sqlmodel import SQLModel

# `alembic upgrade head` is run from this directory, which is not on the path
# the way an installed package would be. Without this the import below fails
# and the migration cannot find out which database it is migrating.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.config import require_database_url

config = context.config
target_metadata = SQLModel.metadata

# Read, do not repeat. `alembic.ini` used to carry its own copy of the URL,
# which is how it came to send `mcp:mcp` at a database whose password had
# changed -- a migration that authenticates differently from the application
# is a migration that can be pointed at the wrong database (#432).
DATABASE_URL = require_database_url()


def run_migrations_offline():
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(DATABASE_URL)

    async def do():
        async with connectable.connect() as conn:
            await conn.run_sync(
                lambda c: context.configure(connection=c, target_metadata=target_metadata)
            )
            async with context.begin_transaction():
                await context.run_migrations()

    asyncio.run(do())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
