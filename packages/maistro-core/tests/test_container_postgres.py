"""A `postgresql://` URL wires PostgreSQL, and says so when it cannot (#122).

The issue this closes is not "PostgreSQL is unsupported" — it is that
configuring it produced in-memory stores with no error, no warning and no log
line. Correct wiring is half the fix; the other half is that every way of
getting it wrong now fails loudly, at startup, naming what to do.

The wiring tests need a real server (`MAISTRO_TEST_PG_DSN`). The refusal tests
do not, and are the ones that matter most when nobody is watching, so they run
everywhere.
"""

from __future__ import annotations

import pytest

from maistro.container import (
    MIN_POSTGRES_VERSION,
    POSTGRES_SCHEMES,
    _asyncpg_dsn,
    create_container,
)
from maistro.types.config import AgentConfig
from maistro.types.errors import ConfigError

from .persistence.conftest import postgres_dsn


@pytest.fixture(autouse=True)
async def _fresh_pool():
    """Close the process-wide asyncpg pool around every test.

    `maistro.persistence.get_pool` is a singleton, which is right for a
    long-lived server and wrong across tests: the pool is bound to the event
    loop that created it, so the second test to ask for one gets the first
    test's connections on a loop that has closed, and asyncpg answers
    "another operation is in progress".
    """
    from maistro.persistence import close_pool

    await close_pool()
    yield
    await close_pool()


requires_postgres = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


def _config(url: str) -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url)


# ── DSN normalisation ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
        ("postgres://u:p@h:5432/d", "postgres://u:p@h:5432/d"),
        # asyncpg speaks libpq DSNs; SQLAlchemy's `+driver` spelling is not one.
        ("postgresql+asyncpg://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
        # Either driver suffix, not only asyncpg's: the pool opened from this
        # DSN is asyncpg's whichever spelling named the database, and
        # `DB_*`-only deployments resolve to the psycopg one.
        ("postgresql+psycopg://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
    ],
)
def test_sqlalchemy_spelling_is_normalised_for_asyncpg(configured: str, expected: str) -> None:
    assert _asyncpg_dsn(configured) == expected


def test_the_sqlalchemy_prefix_is_only_stripped_once() -> None:
    """A password or database name containing the literal prefix must survive."""
    dsn = _asyncpg_dsn("postgresql+asyncpg://u:p@h:5432/postgresql+asyncpg://")

    assert dsn == "postgresql://u:p@h:5432/postgresql+asyncpg://"


def test_the_scheme_a_db_star_deployment_resolves_to_is_recognised(monkeypatch) -> None:
    """The docker-compose case: five `DB_*` variables and no `DATABASE_URL`.

    This replaces a test that asserted every member of `POSTGRES_SCHEMES`
    starts with one of `POSTGRES_SCHEMES` — true of any tuple, and therefore
    green no matter which spellings were missing. The real question is whether
    the tuple covers what `resolve_database_url` actually produces, so the
    scheme is *measured* here rather than restated: when `sync_url` gained its
    `+psycopg` driver suffix, the tautological version stayed green while the
    container silently fell back to in-memory stores for exactly the
    deployment #187 exists to have fixed.
    """
    from maistro.config.database import resolve_database_url

    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "db.internal")

    resolved = resolve_database_url()

    assert resolved.startswith(POSTGRES_SCHEMES), (
        f"{resolved.split('://', 1)[0]}:// is what a DB_*-only deployment resolves to, "
        "and the container does not recognise it as PostgreSQL"
    )


def test_no_scheme_in_the_tuple_is_a_prefix_of_another() -> None:
    """`startswith` on a tuple takes the first match, and `_asyncpg_dsn`
    strips by name — so a scheme that is a prefix of another would make the
    order of this tuple load-bearing without saying so."""
    for scheme in POSTGRES_SCHEMES:
        others = [s for s in POSTGRES_SCHEMES if s != scheme]
        assert not any(other.startswith(scheme) for other in others), (
            f"{scheme} is a prefix of another entry"
        )


# ── refusals, which need no server ────────────────────────────────


async def test_an_unreachable_server_is_an_error_not_a_fallback() -> None:
    """The whole point of #122: configuring a database that cannot be reached
    must never quietly become in-memory stores."""
    # Port 1 is reserved and never listening.
    config = _config("postgresql://maistro:maistro@127.0.0.1:1/nope")

    with pytest.raises(Exception) as excinfo:
        await create_container(config)

    # Whatever asyncpg raises, it must not be swallowed into a working container.
    assert excinfo.value is not None


@requires_postgres
async def test_an_unmigrated_database_names_the_command_that_fixes_it() -> None:
    """`UndefinedTableError` from inside a request handler is a 500 nobody can
    act on. This is the same fact, at startup, with the remedy attached."""
    import asyncpg

    dsn = postgres_dsn()
    scratch = "maistro_unmigrated_test"
    admin = await asyncpg.connect(dsn)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        await admin.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        await admin.close()

    empty_dsn = dsn.rsplit("/", 1)[0] + f"/{scratch}"
    try:
        with pytest.raises(ConfigError) as excinfo:
            await create_container(_config(empty_dsn))

        message = str(excinfo.value)
        assert "alembic upgrade head" in message
        assert "learnings" in message
    finally:
        admin = await asyncpg.connect(dsn)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        finally:
            await admin.close()


def test_the_supported_floor_is_stated_not_implied() -> None:
    assert MIN_POSTGRES_VERSION == 17


# ── wiring, which needs a migrated server ─────────────────────────


@requires_postgres
async def test_a_postgres_url_wires_postgres_stores() -> None:
    container = await create_container(_config(postgres_dsn()))

    assert container.pg_pool is not None
    assert type(container.quota_tracker).__name__ == "PgQuotaTracker"
    assert type(container.learning_store).__name__ == "PgLearningStore"
    assert type(container.outcome_store).__name__ == "PgOutcomeStore"
    assert type(container.session_store).__name__ == "PgSessionStore"
    assert type(container.audit_log).__name__ == "PgAuditLog"


@requires_postgres
async def test_the_wired_stores_actually_work() -> None:
    """Constructing the right class proves nothing about whether it can run —
    which is exactly how a schema that no migration created went unnoticed."""
    container = await create_container(_config(postgres_dsn()))

    async def total() -> int:
        rows = {r["provider"]: r for r in await container.quota_tracker.get_all_usage()}
        row = rows.get("conformance")
        return int(row["total_tokens"]) if row else 0

    # Asserted as a delta, not an absolute. This database is durable — that is
    # the entire point of the change — so rows from an earlier run are still
    # there, and a test that assumed an empty table would be testing that the
    # store had failed to persist anything.
    before = await total()
    await container.quota_tracker.record_usage(
        provider="conformance", billing_cycle="monthly", input_tokens=7, output_tokens=3
    )

    assert await total() - before == 10


@requires_postgres
async def test_sqlite_is_still_selected_by_a_sqlite_url() -> None:
    """The new branch must not have captured the old one."""
    container = await create_container(_config("sqlite://"))

    assert container.pg_pool is None
    assert container.db_pool is not None
