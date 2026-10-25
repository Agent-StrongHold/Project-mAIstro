"""One place that answers "which database", for the app and for alembic (#432).

Before this there were two literals and nothing reconciled them:

- `server/models/db.py` fell back to
  `postgresql+asyncpg://mcp:mcp@localhost:5441/mcp_orders`
- `alembic.ini` repeated the same string in `sqlalchemy.url`

Port 5441 is published to the host by this package's `docker-compose.yml`, so
that password was a working credential for a reachable service, published in
this repository. It was also *wrong*: #367 had already removed the Compose
profile's committed `POSTGRES_PASSWORD` fallback, and the `mcp:mcp` these two
files sent had never matched it. Both files were dead and insecure at once,
which is what duplication buys.

**`DATABASE_URL` is authoritative, and `POSTGRES_PASSWORD` composes one when it
is unset.** The second half is the point. The Compose profile already requires
`POSTGRES_PASSWORD` and fixes the user, database and published port, and those
three are not secrets -- they are in the tracked Compose file. Asking an
operator to set the password once and then restate it inside a URL is exactly
the duplication that let these two files drift, and the Compose comment saying
"match it in DATABASE_URL" was an instruction to reintroduce it by hand.

`DATABASE_URL` stays authoritative because Compose is not the only way to run
this: pointing the POC at a database somewhere else has to remain expressible.

**Configuring nothing is an error, not localhost.** A default that guesses a
host nobody named turns "you have not configured a database" into "connection
refused", which is a worse message arriving later. This follows the pattern
`maistro.config.database` established for the engine in #187; the POC keeps its
own copy rather than importing it because `server/` has no dependency on
`maistro-core` and acquiring one for six lines would be the larger change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: The parts of the connection the tracked Compose profile fixes. None is a
#: secret -- all three are readable in `docker-compose.yml` -- so composing
#: them here duplicates nothing that matters. `5441` is the *host* port that
#: profile publishes, not the container's 5432.
_COMPOSE_USER = "mcp"
_COMPOSE_DATABASE = "mcp_orders"
_COMPOSE_HOST = "localhost"
_COMPOSE_PORT = 5441


class ConfigError(RuntimeError):
    """The database was never named, and this process cannot proceed without one."""


def resolve_database_url(env: Mapping[str, str] | None = None) -> str:
    """The configured URL, or `""` when nothing names a database.

    `DATABASE_URL` wins outright. Empty and whitespace-only count as unset:
    a variable set to nothing in a `.env` is how "unset" is usually spelled in
    practice, and taking it as an answer produces a URL with no host.
    """
    environ = os.environ if env is None else env
    explicit = environ.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    password = environ.get("POSTGRES_PASSWORD", "").strip()
    if password:
        return (
            f"postgresql+asyncpg://{_COMPOSE_USER}:{password}"
            f"@{_COMPOSE_HOST}:{_COMPOSE_PORT}/{_COMPOSE_DATABASE}"
        )
    return ""


def require_database_url(env: Mapping[str, str] | None = None) -> str:
    """`resolve_database_url`, but an unconfigured database raises."""
    url = resolve_database_url(env)
    if not url:
        msg = (
            "No database configured. Set POSTGRES_PASSWORD to the password "
            "docker-compose.yml starts PostgreSQL with, or set DATABASE_URL to a "
            "full postgresql+asyncpg:// URL to reach a database elsewhere. See "
            "this package's README -- neither has a default, because guessing "
            "localhost would report a connection failure instead of a missing "
            "setting (#432)."
        )
        raise ConfigError(msg)
    return url
