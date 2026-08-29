"""SPEC-082926-730d: one asyncpg pool per database, with exactly one owner (#335).

`create_container` used to take the URL branch even when handed a pool: it
opened a second one, built the learnings/outcome/session/quota stores against
it, and then preferred the *supplied* pool for everything downstream. Two pools,
one database, the stores split across them, and neither with an owner.

These count pools rather than asserting on prose. The counting is the point: the
leak was invisible precisely because nothing counted, and `get_pool` was a
process singleton that ignored its argument, so in one process the "second" pool
was usually the same object.

The registry tests run anywhere — they are about a dict. The container tests need
a migrated PostgreSQL (`MAISTRO_TEST_PG_DSN`), because "how many pools did
building a container open" is only answerable when the container actually
builds, and a fake deep enough to get through the execution spine would be
answering the question itself.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

import maistro.persistence as persistence_module
from maistro.container import Container, create_container
from maistro.persistence import close_pool, get_pool, pool_count
from maistro.types.config import AgentConfig
from maistro.types.errors import ConfigError

from .persistence.conftest import postgres_dsn, requires_postgres

#: Captured at import, before any fixture patches it. A test that builds its own
#: pool through the patched name would be counted as the container's, which is
#: exactly the confusion these tests exist to rule out.
_create_pool = asyncpg.create_pool

DSN = "postgresql://user:pass@localhost:5432/maistro"
OTHER_DSN = "postgresql://user:pass@localhost:5432/other"


class FakePool:
    """Counts its own closes, so "closed exactly once" is checkable."""

    def __init__(self, *, close_raises: bool = False) -> None:
        self.closes = 0
        self._close_raises = close_raises

    async def close(self) -> None:
        self.closes += 1
        if self._close_raises:
            raise RuntimeError("the pool refused to close")

    @property
    def closed(self) -> bool:
        return self.closes > 0


@pytest.fixture(autouse=True)
async def _empty_registry() -> Any:
    persistence_module._pools.clear()
    yield
    await close_pool()
    persistence_module._pools.clear()


@pytest.fixture
def created_pools() -> Any:
    """Replace `asyncpg.create_pool` with a counting factory over fake pools."""
    made: list[FakePool] = []

    async def factory(*_args: Any, **_kwargs: Any) -> FakePool:
        pool = FakePool()
        made.append(pool)
        return pool

    with patch("maistro.persistence.asyncpg.create_pool", new=factory):
        yield made


@pytest.fixture
def opened() -> Any:
    """Count real pools without replacing them.

    Wrapping rather than faking: the container walks the pool deeply enough
    (preflight, schema probe, execution spine) that a stand-in would be a second
    implementation of PostgreSQL rather than a test double.
    """
    made: list[Any] = []

    async def counting(*args: Any, **kwargs: Any) -> Any:
        pool = await _create_pool(*args, **kwargs)
        made.append(pool)
        return pool

    with patch("maistro.persistence.asyncpg.create_pool", new=counting):
        yield made


def _config(url: str | None = None) -> AgentConfig:
    return AgentConfig(router_api_key="test-key", database_url=url or postgres_dsn())


async def _build(**kwargs: Any) -> Container:
    return await create_container(_config(), **kwargs)


async def _ephemeral_container(pool: Any, *, owned: bool) -> Container:
    """A container with no database, holding a pool it may or may not own.

    `aclose` is about ownership, not about PostgreSQL, so these cases do not
    need a server -- but they do need a real `Container`, which has a dozen
    required collaborators. Building one through `create_container` on
    `memory://` is cheaper than a hand-rolled stand-in and cannot drift from
    the real constructor.
    """
    container = await create_container(_config("memory://"))
    container.pg_pool = pool
    container.owns_pg_pool = owned
    return container


async def _real_pool() -> Any:
    """A pool of the caller's own, the way a product that injects one gets it."""
    return await _create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=persistence_module._register_json_codecs
    )


# --- AC-1: a supplied pool prevents a second one -----------------------------


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-1")
@pytest.mark.asyncio
async def test_a_supplied_pool_prevents_a_second_pool_for_the_same_database(
    opened: list[Any],
) -> None:
    """The defect, counted. Before #335 this opened one anyway."""
    supplied = await _real_pool()
    try:
        container = await _build(pg_pool=supplied)

        assert opened == [], "a pool was opened alongside the supplied one"
        assert pool_count() == 0
        assert container.pg_pool is supplied
    finally:
        await supplied.close()


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-1")
@pytest.mark.asyncio
async def test_a_url_with_no_supplied_pool_opens_exactly_one(opened: list[Any]) -> None:
    container = await _build()
    try:
        assert len(opened) == 1
        assert container.pg_pool is opened[0]
    finally:
        await container.aclose()


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-1")
@pytest.mark.asyncio
async def test_the_stores_and_the_events_hold_the_same_pool(opened: list[Any]) -> None:
    """The split that made two pools survivable: the URL-built stores held one
    and everything downstream held the other."""
    supplied = await _real_pool()
    try:
        container = await _build(pg_pool=supplied)

        assert container.session_store._pool is supplied  # type: ignore[attr-defined]
        assert container.quota_tracker._pool is supplied  # type: ignore[attr-defined]
        assert container.pg_pool is supplied
    finally:
        await supplied.close()


# --- AC-2: ownership is recorded ---------------------------------------------


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-2")
@pytest.mark.asyncio
async def test_a_container_owns_the_pool_it_opened() -> None:
    container = await _build()
    try:
        assert container.owns_pg_pool is True
    finally:
        await container.aclose()


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-2")
@pytest.mark.asyncio
async def test_a_container_does_not_own_a_supplied_pool() -> None:
    supplied = await _real_pool()
    try:
        container = await _build(pg_pool=supplied)
        assert container.owns_pg_pool is False
    finally:
        await supplied.close()


# --- AC-3: the owner closes ---------------------------------------------------


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_closing_the_container_closes_the_pool_it_opened(opened: list[Any]) -> None:
    container = await _build()

    await container.aclose()

    assert opened[0]._closed is True
    assert container.pg_pool is None
    assert pool_count() == 0, "a closed pool left in the registry is handed to the next caller"


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_closing_the_container_leaves_a_supplied_pool_open() -> None:
    supplied = await _real_pool()
    try:
        container = await _build(pg_pool=supplied)

        await container.aclose()

        assert supplied._closed is False
        assert await supplied.fetchval("SELECT 1") == 1
    finally:
        await supplied.close()


@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_closing_twice_closes_once() -> None:
    """No database needed: this is about `aclose`, and a fake pool counts."""
    pool = FakePool()
    container = await _ephemeral_container(pool, owned=True)

    await container.aclose()
    await container.aclose()

    assert pool.closes == 1


@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_a_close_that_raises_still_leaves_the_container_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A shutdown that stops at the first failure leaves everything after it
    unreleased, and a caller that retries hits a pool already going down."""
    container = await _ephemeral_container(FakePool(close_raises=True), owned=True)

    await container.aclose()

    assert container.closed is True
    assert container.pg_pool is None
    assert "did not close cleanly" in caplog.text


@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_closing_a_container_that_owns_nothing_is_a_no_op() -> None:
    pool = FakePool()
    container = await _ephemeral_container(pool, owned=False)

    await container.aclose()

    assert pool.closes == 0
    assert container.pg_pool is pool


# --- AC-4: a failed preflight leaves nothing behind ---------------------------


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-4")
@pytest.mark.asyncio
async def test_a_failed_preflight_leaves_no_pool_open(opened: list[Any]) -> None:
    """The pool it opened has no container to belong to."""
    with (
        patch(
            "maistro.container._require_postgres_schema",
            new=AsyncMock(side_effect=ConfigError("unmigrated")),
        ),
        pytest.raises(ConfigError),
    ):
        await _build()

    assert len(opened) == 1
    assert opened[0]._closed is True
    assert pool_count() == 0


@requires_postgres
@pytest.mark.ac("SPEC-082926-730d/AC-4")
@pytest.mark.asyncio
async def test_a_failed_preflight_does_not_close_a_supplied_pool() -> None:
    """It is the caller's. Closing it turns a configuration error into a broken
    caller, which is the mirror-image of the leak this issue is about."""
    supplied = await _real_pool()
    try:
        with (
            patch(
                "maistro.container._require_postgres_schema",
                new=AsyncMock(side_effect=ConfigError("unmigrated")),
            ),
            pytest.raises(ConfigError),
        ):
            await _build(pg_pool=supplied)

        assert supplied._closed is False
        assert await supplied.fetchval("SELECT 1") == 1
    finally:
        await supplied.close()


# --- AC-5: the registry is per database ---------------------------------------


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_two_databases_get_two_pools(created_pools: list[FakePool]) -> None:
    """`get_pool` ignored its argument after the first call, so this returned
    the first database's connections for the second database's DSN."""
    first = await get_pool(DSN)
    second = await get_pool(OTHER_DSN)

    assert first is not second
    assert pool_count() == 2


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_one_database_gets_one_pool(created_pools: list[FakePool]) -> None:
    assert await get_pool(DSN) is await get_pool(DSN)
    assert pool_count() == 1


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_closing_one_database_leaves_the_other_open(
    created_pools: list[FakePool],
) -> None:
    first = await get_pool(DSN)
    second = await get_pool(OTHER_DSN)

    await close_pool(DSN)

    assert first.closes == 1
    assert second.closes == 0
    assert await get_pool(DSN) is not first, "a closed pool was handed out again"


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_closing_with_no_argument_closes_every_pool(
    created_pools: list[FakePool],
) -> None:
    """What every caller of the old single-pool form meant."""
    await get_pool(DSN)
    await get_pool(OTHER_DSN)

    await close_pool()

    assert [pool.closes for pool in created_pools] == [1, 1]
    assert pool_count() == 0


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_a_pool_is_registered_only_after_it_exists() -> None:
    """Recording a not-yet-created pool would hand a racing caller a `None`."""
    seen: list[int] = []

    async def slow_factory(*_args: Any, **_kwargs: Any) -> FakePool:
        seen.append(pool_count())
        return FakePool()

    with patch("maistro.persistence.asyncpg.create_pool", new=slow_factory):
        await get_pool(DSN)

    assert seen == [0]


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_an_impossible_size_is_refused_before_a_pool_is_opened() -> None:
    create = AsyncMock()
    with (
        patch("maistro.persistence.asyncpg.create_pool", new=create),
        pytest.raises(ValueError, match="exceeds max_size"),
    ):
        await get_pool(DSN, min_size=10, max_size=1)

    create.assert_not_awaited()
    assert pool_count() == 0


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_closing_an_unknown_database_is_a_no_op(created_pools: list[FakePool]) -> None:
    """A container that already closed its own pool calls this on shutdown."""
    await get_pool(DSN)

    await close_pool(OTHER_DSN)

    assert pool_count() == 1
    assert created_pools[0].closes == 0


@pytest.mark.ac("SPEC-082926-730d/AC-5")
@pytest.mark.asyncio
async def test_forgetting_an_unregistered_pool_leaves_the_registry_alone(
    created_pools: list[FakePool],
) -> None:
    """A supplied pool was never registered, and `aclose` must not care."""
    registered = await get_pool(DSN)

    persistence_module.forget_pool(FakePool())

    assert pool_count() == 1
    assert await get_pool(DSN) is registered
