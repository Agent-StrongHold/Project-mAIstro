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

**Only the tests that run anywhere carry `@pytest.mark.ac`.** `ac_outcome_plugin`
sinks a criterion when any test claiming it skips, and rightly: an
environment-gated test that never ran is not evidence the criterion holds. So
staking a criterion on a `requires_postgres` test would report it *unproven*
wherever the database is absent — which is what left AC-1 through AC-4 sitting
at `covered` while reading as proven. The PostgreSQL tests are corroboration,
against the real thing; the marked tests are the evidence.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

import maistro.container as container_module
import maistro.persistence as persistence_module
from maistro.container import Container, create_container
from maistro.persistence import close_pool, get_pool, pool_count, release_pool
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
    persistence_module._users.clear()
    yield
    await close_pool()
    persistence_module._pools.clear()
    persistence_module._users.clear()


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


async def _ephemeral_container(pool: Any, *, held: bool) -> Container:
    """A container with no database, holding a pool it may or may not have taken.

    `aclose` is about ownership, not about PostgreSQL, so these cases do not
    need a server -- but they do need a real `Container`, which has a dozen
    required collaborators. Building one through `create_container` on
    `memory://` is cheaper than a hand-rolled stand-in and cannot drift from
    the real constructor.
    """
    container = await create_container(_config("memory://"))
    container.pg_pool = pool
    container.holds_pg_pool = held
    if held and not any(p is pool for p in persistence_module._pools.values()):
        # A held pool is one `get_pool` handed out, so it is registered. Setting
        # the flag without registering would build a container that cannot
        # occur, and `aclose` would then be tested against a state it never
        # meets in production.
        persistence_module._pools.setdefault(f"registered://{id(pool)}", pool)
        persistence_module._users[f"registered://{id(pool)}"] = 1
    return container


async def _real_pool() -> Any:
    """A pool of the caller's own, the way a product that injects one gets it."""
    return await _create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=persistence_module._register_json_codecs
    )


# Each criterion below is proved twice: once against the registry or an
# ephemeral container, which runs anywhere, and once against a real migrated
# PostgreSQL. The first kind is not a weaker version of the second — a claim
# whose only evidence skips wherever the database is absent is a claim the
# gates cannot see, which is how AC-1 through AC-4 sat at `covered` while
# reading as proven.


@pytest.mark.ac("SPEC-082926-730d/AC-1")
@pytest.mark.asyncio
async def test_one_dsn_yields_one_pool_however_many_ask(
    created_pools: list[FakePool],
) -> None:
    """The registry half of "one pool per database", with no server needed."""
    first = await get_pool(DSN)
    second = await get_pool(DSN)

    assert first is second
    assert len(created_pools) == 1
    assert pool_count() == 1


@pytest.mark.ac("SPEC-082926-730d/AC-2")
@pytest.mark.asyncio
async def test_a_supplied_pool_is_not_held(created_pools: list[FakePool]) -> None:
    """A pool the caller passed in is theirs; the container only borrows it."""
    supplied = FakePool()
    container = await _ephemeral_container(supplied, held=False)

    assert container.holds_pg_pool is False
    assert container.pg_pool is supplied


@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_the_pool_survives_until_the_last_holder_lets_go(
    created_pools: list[FakePool],
) -> None:
    """The finding: two containers built from one DSN get the *same* pool.

    Under "whoever opened it closes it" the first `aclose` would close the pool
    the second container's stores are still using, and their next query would
    fail somewhere far from the mistake (Codex, #335).
    """
    shared = await get_pool(DSN)
    second_holder = await get_pool(DSN)
    assert second_holder is shared

    first = await _ephemeral_container(shared, held=True)
    second = await _ephemeral_container(shared, held=True)

    await first.aclose()

    assert shared.closes == 0, "the pool closed while another container still held it"
    assert pool_count() == 1

    await second.aclose()

    assert shared.closes == 1
    assert pool_count() == 0, "a closed pool left registered is handed to the next caller"


@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_releasing_an_unregistered_pool_is_a_no_op(
    created_pools: list[FakePool],
) -> None:
    """A supplied pool, and one already force-closed, both reach here.

    Neither caller is doing anything wrong, so this must not raise — and must
    not close a pool the registry never handed out.
    """
    stranger = FakePool()

    assert await release_pool(stranger) is False
    assert stranger.closes == 0


@pytest.mark.ac("SPEC-082926-730d/AC-4")
@pytest.mark.asyncio
async def test_every_pool_is_closed_even_when_one_close_fails(
    created_pools: list[FakePool],
) -> None:
    """Stopping at the first failure leaves the rest open *and* unreachable.

    The registry is cleared before the closes begin, so an early return breaks
    the close-all contract precisely on the error path that most needs it to
    hold (Codex, #335).
    """
    first = await get_pool(DSN)
    second = await get_pool(OTHER_DSN)
    first._close_raises = True

    with pytest.raises(ExceptionGroup):
        await close_pool()

    assert first.closes == 1
    assert second.closes == 1, "a later pool was left open by an earlier failure"
    assert pool_count() == 0


@pytest.mark.ac("SPEC-082926-730d/AC-4")
@pytest.mark.asyncio
async def test_the_raised_group_carries_every_failure(
    created_pools: list[FakePool],
) -> None:
    """One failure must not hide another: an operator fixing a shutdown needs
    all of them, not the first."""
    first = await get_pool(DSN)
    second = await get_pool(OTHER_DSN)
    first._close_raises = True
    second._close_raises = True

    with pytest.raises(ExceptionGroup) as raised:
        await close_pool()

    assert len(raised.value.exceptions) == 2


@pytest.mark.ac("SPEC-082926-730d/AC-1")
@pytest.mark.asyncio
async def test_a_supplied_pool_means_the_registry_is_never_asked() -> None:
    """The headline claim, at the seam, with no server involved.

    `_wire_postgres_backend` is where the second pool was opened: it called
    `get_pool` unconditionally and the *caller's* pool was preferred later, so
    the stores it built held one pool while everything downstream held another.

    Asserting "get_pool was not called" is the whole claim, and it is settled
    before the first connection is used — so the preflight failing on a fake
    pool afterwards is expected and is not what this test is about.
    """
    import maistro.persistence as persistence

    called = False

    async def _explode(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("the registry was asked for a pool despite one being supplied")

    with patch.object(persistence, "get_pool", new=_explode), contextlib.suppress(Exception):
        await container_module._wire_postgres_backend(
            "postgresql://user:pass@localhost:5432/maistro",
            supplied_pool=FakePool(),
        )

    assert called is False


# --- AC-1: a supplied pool prevents a second one -----------------------------


@requires_postgres
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
@pytest.mark.asyncio
async def test_a_url_with_no_supplied_pool_opens_exactly_one(opened: list[Any]) -> None:
    container = await _build()
    try:
        assert len(opened) == 1
        assert container.pg_pool is opened[0]
    finally:
        await container.aclose()


@requires_postgres
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
@pytest.mark.asyncio
async def test_a_container_holds_the_pool_it_took_from_the_registry() -> None:
    container = await _build()
    try:
        assert container.holds_pg_pool is True
    finally:
        await container.aclose()


@requires_postgres
@pytest.mark.asyncio
async def test_a_container_does_not_hold_a_supplied_pool() -> None:
    supplied = await _real_pool()
    try:
        container = await _build(pg_pool=supplied)
        assert container.holds_pg_pool is False
    finally:
        await supplied.close()


# --- AC-3: the owner closes ---------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_closing_the_container_closes_the_pool_it_opened(opened: list[Any]) -> None:
    container = await _build()

    await container.aclose()

    assert opened[0]._closed is True
    assert container.pg_pool is None
    assert pool_count() == 0, "a closed pool left in the registry is handed to the next caller"


@requires_postgres
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
    container = await _ephemeral_container(pool, held=True)

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
    container = await _ephemeral_container(FakePool(close_raises=True), held=True)

    await container.aclose()

    assert container.closed is True
    assert container.pg_pool is None
    assert "did not close cleanly" in caplog.text


@pytest.mark.ac("SPEC-082926-730d/AC-3")
@pytest.mark.asyncio
async def test_closing_a_container_that_holds_nothing_is_a_no_op() -> None:
    pool = FakePool()
    container = await _ephemeral_container(pool, held=False)

    await container.aclose()

    assert pool.closes == 0
    assert container.pg_pool is pool


# --- AC-4: a failed preflight leaves nothing behind ---------------------------


@requires_postgres
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
