"""One resolver for "which database", used by alembic and the container (#187).

Before this there were two, and nothing reconciled them:

- `alembic/env.py` read `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`
  through `DatabaseSettings`.
- `maistro.container` read `DATABASE_URL`.

So an operator who set only `DB_*` got `alembic upgrade head` applying the whole
chain to the database they configured, and a container that saw an empty
`database_url`, took the ephemeral branch, and ran entirely in memory. Both
commands succeeded. The schema was correct. The data was discarded on every
restart.

That is not hypothetical: `docker-compose.yml` gives the `maistro-engine`
service exactly those five `DB_*` variables and no `DATABASE_URL`, so the
shipped default starts a PostgreSQL container with a volume, waits on its health
check, and then connects to none of it.

**`DATABASE_URL` is authoritative, and `DB_*` composes one when it is unset.**
The direction is forced rather than chosen: `DB_*` can only ever name a
PostgreSQL server -- `DatabaseSettings.url` hardcodes the scheme -- so making it
the authoritative source would make `sqlite:` and `memory://` inexpressible.
`DATABASE_URL` can say all three.

**Configuring nothing is no longer the same as configuring localhost.**
`DatabaseSettings` defaults every field, so before this `alembic upgrade head`
with an empty environment silently targeted
`postgresql://maistro:maistro@localhost:5432/maistro`. A tool that cannot run
without a database should say so rather than guess one, which is why
`require_database_url` exists alongside `resolve_database_url`: the container may
legitimately run with nothing configured (in-memory, and it warns), and alembic
may not.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from maistro.types.errors import ConfigError

#: The `DB_*` names `DatabaseSettings` reads, without its `DB_` prefix.
#:
#: Presence is checked against the real environment rather than by constructing
#: `DatabaseSettings` and comparing to its defaults: every field has one, so a
#: deployment that deliberately set `DB_USER=maistro` would be indistinguishable
#: from one that set nothing.
_DB_FIELDS: Final = ("HOST", "PORT", "NAME", "USER", "PASSWORD")

#: Schemes alembic can migrate. `memory://` and `sqlite:` are legitimate
#: `database_url` values for the container and meaningless to a migration that
#: writes JSONB and depends on the `vector` extension.
_MIGRATABLE_SCHEMES: Final = ("postgresql://", "postgres://", "postgresql+asyncpg://")


def _db_env_is_set(env: Mapping[str, str]) -> bool:
    """True when the deployment configured any `DB_*` variable at all."""
    return any(env.get(f"DB_{field}") for field in _DB_FIELDS)


def _compose_from_db_env() -> str:
    """Build a `postgresql://` URL from `DatabaseSettings`.

    Imported lazily because `DatabaseSettings` pulls in pydantic-settings, and
    this module is imported by `alembic/env.py` on a path where the failure to
    import would be reported as a migration error rather than a config one.
    """
    from maistro.config.settings import DatabaseSettings

    return DatabaseSettings().sync_url


def resolve_database_url(env: Mapping[str, str] | None = None) -> str:
    """The one answer to "which database", for every caller.

    Precedence, and each rung is deliberate:

    1. `DATABASE_URL` — the only form that can express a non-PostgreSQL backend,
       and the convention every hosting platform hands out.
    2. Any `DB_*` set — composed into a `postgresql://` URL. This is what makes
       the shipped `docker-compose.yml` durable without editing it: the five
       variables it already passes now reach the container too.
    3. Empty — nothing was configured. The container warns and runs ephemeral;
       `require_database_url` raises for callers that cannot.

    An empty-but-present `DATABASE_URL=` falls through to `DB_*` rather than
    being taken as an answer, because a variable set to nothing in a compose
    file or a `.env` is how "unset" is usually spelled in practice.
    """
    environ = os.environ if env is None else env
    explicit = environ.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    if _db_env_is_set(environ):
        return _compose_from_db_env()
    return ""


def require_database_url(env: Mapping[str, str] | None = None) -> str:
    """`resolve_database_url`, but a missing or unmigratable database is an error.

    For callers that cannot proceed without one -- alembic above all. Guessing
    `localhost` on their behalf turns "you did not configure a database" into
    "connection refused to a host you never named", which is the same class of
    misdirection this module exists to remove.
    """
    url = resolve_database_url(env)
    if not url:
        msg = (
            "No database configured. Set DATABASE_URL to a "
            "postgresql://user:pass@host/db URL, or set the DB_HOST/DB_PORT/"
            "DB_NAME/DB_USER/DB_PASSWORD variables that compose one. Migrations "
            "cannot run against a database that was never named -- see #187."
        )
        raise ConfigError(msg)
    if not url.startswith(_MIGRATABLE_SCHEMES):
        from maistro.container import _redact_url

        msg = (
            f"database_url {_redact_url(url)!r} is not a PostgreSQL URL, and the "
            "migration chain writes JSONB and depends on the `vector` extension. "
            "Migrations require postgresql://; sqlite: and memory:// are runtime "
            "choices for the container only."
        )
        raise ConfigError(msg)
    return url


def to_sync_url(database_url: str) -> str:
    """Strip the async driver suffix for SQLAlchemy's synchronous engine.

    `DatabaseSettings` exposes both `url` (`postgresql+asyncpg://`) and
    `sync_url`, and an operator may reasonably have set either spelling in
    `DATABASE_URL`. Alembic drives a sync engine, which cannot load asyncpg --
    it raises `InvalidRequestError: The asyncio extension requires an async
    driver` rather than connecting.
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
