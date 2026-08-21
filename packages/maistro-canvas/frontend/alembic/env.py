from alembic import context
from sqlmodel import SQLModel

config = context.config
target_metadata = SQLModel.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))

    async def do():
        async with connectable.connect() as conn:
            await conn.run_sync(
                lambda c: context.configure(connection=c, target_metadata=target_metadata)
            )
            async with context.begin_transaction():
                await context.run_migrations()

    import asyncio

    asyncio.run(do())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
