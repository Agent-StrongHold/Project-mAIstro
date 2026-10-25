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
    """The one resolved database URL, shared with the container (#187).

    This used to read `DatabaseSettings` directly, which meant alembic and
    `maistro.container` answered "which database" from different environment
    variables with nothing reconciling them: setting only `DB_*` -- what
    `docker-compose.yml` does -- migrated one database and then ran with
    in-memory stores. `require_database_url` is the shared answer, and it
    raises rather than falling back to the `DatabaseSettings` defaults, so an
    empty environment reports "no database configured" instead of a connection
    error against a `localhost` nobody asked for.
    """
    from maistro.config.database import require_database_url, to_sync_url

    return to_sync_url(require_database_url())


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
