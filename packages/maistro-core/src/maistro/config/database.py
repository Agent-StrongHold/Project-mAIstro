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
    """True when the deployment configured any `DB_*` variable at all.

    Presence, not truthiness. `DB_PASSWORD=` is how a deployment spells
    "passwordless PostgreSQL", and reading that as unset sent alembic to "No
    database configured" and permissive callers to in-memory -- while the
    environment had explicitly said which database to use.
    """
    return any(f"DB_{field}" in env for field in _DB_FIELDS)


def _compose_from_db_env(env: Mapping[str, str]) -> str:
    """Build a `postgresql://` URL from the `DB_*` fields in `env`.

    The mapping is passed through rather than left to `DatabaseSettings()`'s
    own environment read: a caller who supplies `env` is saying "resolve
    against this", and reading `os.environ` instead would answer about a
    different database entirely. Fields absent from the mapping still fall back
    to `DatabaseSettings`' resolution and defaults, which is what makes the
    default `env is os.environ` path behave exactly as before.

    Imported lazily because `DatabaseSettings` pulls in pydantic-settings, and
    this module is imported by `alembic/env.py` on a path where a failure to
    import would be reported as a migration error rather than a config one.
    """
    from maistro.config.settings import DatabaseSettings

    overrides = {field.lower(): env[f"DB_{field}"] for field in _DB_FIELDS if f"DB_{field}" in env}
    if not overrides:
        return DatabaseSettings().sync_url
    # Re-validated rather than `DatabaseSettings(**overrides)`: pydantic-settings
    # types `__init__`'s keyword arguments for its own `_env_*` controls, so a
    # `**dict[str, str]` splat does not type-check. Going through
    # `model_validate` also coerces `port` back to an int, which a raw
    # `model_copy(update=...)` would leave as the string the environment held.
    base = DatabaseSettings().model_dump()
    return DatabaseSettings.model_validate({**base, **overrides}).sync_url


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
        return _compose_from_db_env(environ)
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
    """Normalise to the spelling SQLAlchemy's synchronous engine can load.

    Two conversions, and both are load-bearing:

    - `postgresql+asyncpg://` -> `postgresql://`. `DatabaseSettings` exposes
      both spellings and an operator may reasonably have set either. Alembic
      drives a sync engine, which cannot load asyncpg -- it raises
      `InvalidRequestError: The asyncio extension requires an async driver`
      rather than connecting.
    - `postgres://` -> `postgresql://`. SQLAlchemy 2 removed the legacy
      `postgres` dialect alias, so passing it through reaches
      `create_engine` and fails on dialect lookup before any connection is
      attempted. `_MIGRATABLE_SCHEMES` accepts `postgres://` because hosted
      providers still hand it out; accepting it and then failing to load it
      would be worse than rejecting it.
    """
    return _normalise_postgres_scheme(database_url, "postgresql://")


def to_async_url(database_url: str) -> str:
    """Normalise to the spelling SQLAlchemy's *async* engine can load.

    The mirror of `to_sync_url`, for `memory.store.get_engine`, which builds an
    `AsyncEngine`. A bare `postgresql://` there selects psycopg2 and raises
    rather than connecting, so a deployment that set the obvious spelling got a
    silent `None` engine.

    Non-PostgreSQL URLs pass through untouched: this function's job is the
    driver suffix, not inventing an async driver for a backend that may not
    have one wired.
    """
    return _normalise_postgres_scheme(database_url, "postgresql+asyncpg://")


def _normalise_postgres_scheme(database_url: str, target: str) -> str:
    """Rewrite whichever PostgreSQL spelling this URL uses to `target`."""
    for scheme in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if database_url.startswith(scheme):
            return target + database_url[len(scheme) :]
    return database_url
