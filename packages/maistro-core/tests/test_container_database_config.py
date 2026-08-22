"""A configured database that cannot be wired must fail loudly (#122).

Before this, every scheme except `sqlite:` fell through to in-memory stores. A
deployment set to `postgresql://…` therefore ran with learnings, outcomes,
sessions and quota that vanish on restart, and nothing said so — no error, no
warning, no log line. A misconfigured model gives visibly wrong answers; a
misconfigured database gives correct answers that quietly disappear.

The three cases are deliberately distinguished, and the distinction is the
design: unset is honest, `memory://` is chosen, anything else is a mistake.
"""

from __future__ import annotations

import logging

import pytest

from maistro.container import create_container
from maistro.types import AgentConfig
from maistro.types.errors import ConfigError


def _config(url: str) -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pw@host:5432/maistro",
        "postgres://host/db",
        "mysql://host/db",
        "redis://host:6379",
        "not-a-url",
    ],
)
async def test_a_database_that_cannot_be_wired_is_a_config_error(url: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        await create_container(_config(url))
    message = str(excinfo.value)
    assert url in message, "the message must name the offending value"
    assert "sqlite://" in message and "memory://" in message, "and the supported alternatives"


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


async def test_sqlite_still_wires_the_durable_backend() -> None:
    container = await create_container(_config("sqlite://"))
    assert container is not None
