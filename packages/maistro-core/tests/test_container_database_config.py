"""A configured database that cannot be wired must fail loudly (#122).

Before this, every scheme except `sqlite:` fell through to in-memory stores. A
deployment set to `postgresql://…` therefore ran with learnings, outcomes,
sessions and quota that vanish on restart, and nothing said so — no error, no
warning, no log line. A misconfigured model gives visibly wrong answers; a
misconfigured database gives correct answers that quietly disappear.

The three cases are deliberately distinguished, and the distinction is the
design: unset is honest, `memory://` is chosen, anything else is a mistake.

`postgresql://` was in the "mistake" list until #122 gave it a backend, and it
moved rather than being deleted: the rejection message still has to name it, or
an operator reading it learns that the durable system of record is unsupported.
The PostgreSQL path's own credential redaction is exercised against a live
server in `tests/migrations/test_pg_store_wiring.py`, where a refused
connection is a real error rather than a DNS timeout.
"""

from __future__ import annotations

import logging

import pytest

from maistro.container import _redact_url, create_container
from maistro.types import AgentConfig
from maistro.types.errors import ConfigError


def _config(url: str) -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "mysql://host/db",
        "redis://host:6379",
        "not-a-url",
    ],
)
async def test_a_database_that_cannot_be_wired_is_a_config_error(url: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config(url))
    message = str(excinfo.value)
    assert _redact_url(url) in message, "the message must name the offending value"
    assert "sqlite://" in message and "memory://" in message, "and the supported alternatives"


async def test_the_error_names_postgresql_among_the_supported_backends() -> None:
    """PostgreSQL is the durable system of record (ADR-082226-5104). An error
    that lists only sqlite tells an operator the opposite of what is true."""
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config("mysql://host/db"))

    assert "postgresql://" in str(excinfo.value)


@pytest.mark.parametrize(
    ("url", "leaked"),
    [
        ("mysql://root:hunter2@db/app", "hunter2"),
        ("mysql://alice:pw@host:3306/app", "alice"),
        ("redis://:onlyapassword@cache:6379", "onlyapassword"),
    ],
)
async def test_rejected_urls_do_not_leak_credentials(url: str, leaked: str) -> None:
    """This error is uncaught at startup, so it lands in process logs and
    whatever collects them. PostgreSQL URLs carry `user:password@` as a matter
    of course — the first version of this check put them in the logs of every
    deployment that hit it, while fixing a different silent-failure bug."""
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config(url))

    assert leaked not in str(excinfo.value)


async def test_a_rejected_url_stays_diagnosable() -> None:
    """Redaction that removed the scheme and host would trade one unusable
    error for another."""
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config("mysql://user:pw@db.internal:3306/maistro"))

    message = str(excinfo.value)
    assert "mysql" in message
    assert "db.internal:3306" in message
    assert "/maistro" in message


@pytest.mark.parametrize("url", ["mysql://host/db", "redis://host:6379"])
async def test_a_url_without_credentials_is_reported_intact(url: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config(url))

    assert url in str(excinfo.value)


def test_an_unparseable_url_is_not_echoed() -> None:
    """A string urlsplit cannot read is a string this cannot promise to redact."""
    redacted = _redact_url("postgresql://user:pw@[not-an-ipv6/db")

    assert "pw" not in redacted
    assert redacted.startswith("postgresql:")


async def test_memory_scheme_selects_ephemeral_stores_without_complaint(caplog) -> None:
    """Chosen ephemerality is not a degraded mode, so it must not warn."""
    with caplog.at_level(logging.WARNING, logger="maistro.container"):
        container = await create_container(_config("memory://"))
    assert container is not None
    assert not [r for r in caplog.records if "in-memory stores" in r.getMessage()]


async def test_an_unset_database_warns_that_state_is_ephemeral(caplog) -> None:
    """Unset is legitimate — no database was asked for — but an operator who
    meant to configure one should be able to see that it did not take."""
    with caplog.at_level(logging.WARNING, logger="maistro.container"):
        container = await create_container(_config(""))
    assert container is not None
    warnings = [r.getMessage() for r in caplog.records if "in-memory stores" in r.getMessage()]
    assert warnings, "an unset database_url must say that nothing survives a restart"
    assert "restart" in warnings[0]


async def test_sqlite_with_a_path_wires_the_durable_backend(tmp_path) -> None:
    container = await create_container(_config(f"sqlite:///{tmp_path}/maistro.db"))
    assert container is not None


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///"])
async def test_pathless_sqlite_is_allowed_but_warned(url: str, caplog) -> None:
    """`_wire_sqlite_backend` reduces a pathless URL to `:memory:`, so it is
    genuinely ephemeral — and unlike `memory://`, the name says the opposite.
    `memory://` is silent because it announces what it does; this does not."""
    with caplog.at_level(logging.WARNING, logger="maistro.container"):
        container = await create_container(_config(url))

    assert container is not None
    warnings = [r.getMessage() for r in caplog.records if "in-memory" in r.getMessage()]
    assert warnings, "a pathless sqlite URL must say it does not survive a restart"
    assert "sqlite:///path/to/file.db" in warnings[0], "and name the durable form"


async def test_the_error_advertises_a_form_that_is_actually_durable() -> None:
    """The first version pointed operators at bare `sqlite://` as the durable
    alternative, which is in-memory."""
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config("mysql://host/db"))

    assert "sqlite:///path/to/file.db" in str(excinfo.value)
