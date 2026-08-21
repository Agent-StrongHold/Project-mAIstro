"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Import models so Alembic can detect them
from maistro.memory.store import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Get database URL from settings (avoids hardcoded credentials)."""
    from maistro.config.settings import DatabaseSettings

    db = DatabaseSettings()
    return db.sync_url


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
