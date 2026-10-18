"""Container publication, explicit reset, and teardown share one lifecycle."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from maistro import container as container_module
from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    configure_default_effect_context,
    default_effect_context,
    new_effect_context,
    release_default_effect_context,
)
from maistro.container import create_container
from maistro.persistence import get_pool, pool_count, release_pool
from maistro.quota.default_tracker import (
    get_default_quota_tracker,
    set_default_quota_tracker,
)
from maistro.types.config import AgentConfig, ModelBindingConfig
from maistro.types.errors import ConfigError

from .persistence.conftest import postgres_dsn

requires_postgres = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


@pytest.fixture
async def _clean_pg_pool_registry() -> AsyncIterator[None]:
    """Start and end each registry-counting test with an empty pool registry.

    `maistro.persistence` keeps one process-global registry: a pool a previous
    test leaked is handed back to the next, along with whatever event loop it
    was created on. `close_pool()` clears it unconditionally, so these tests
    measure only the pools their own `create_container` call opens -- and
    leave nothing behind for the suite that follows.
    """
    from maistro.persistence import close_pool

    await close_pool()
    yield
    await close_pool()


def _failing_config(database_url: str = "memory://") -> AgentConfig:
    """Config whose real model-binding bootstrap must reject at startup.

    The rejection is the production one (#1079 Finding 4): a declared Binding
    naming a credential ref no production surface can register. Bootstrap is
    never mocked into a no-op here -- the ConfigError these tests catch is the
    real one.
    """
    return AgentConfig(
        router_api_key="test-key",
        database_url=database_url,
        model_bindings=[
            ModelBindingConfig(
                binding_id="bad", project_id="p", credential_refs=("unregistrable-ref",)
            )
        ],
    )


@pytest.fixture(autouse=True)
def _isolated_default_context() -> Iterator[None]:
    default_effect_context.cache_clear()
    set_default_quota_tracker(None)
    yield
    default_effect_context.cache_clear()
    set_default_quota_tracker(None)


@pytest.mark.parametrize("close_inner_first", [True, False], ids=["nested", "out-of-order"])
async def test_container_lifetimes_preserve_the_other_live_context(close_inner_first: bool) -> None:
    config = AgentConfig(router_api_key="test-key", database_url="memory://")
    outer = await create_container(config)
    try:
        inner = await create_container(config)
        try:
            assert default_effect_context() is inner.capability_effects
            first, remaining = (inner, outer) if close_inner_first else (outer, inner)
            await first.aclose()
            assert default_effect_context() is remaining.capability_effects
            await first.aclose()
            assert default_effect_context() is remaining.capability_effects
        finally:
            await inner.aclose()
    finally:
        await outer.aclose()
    fallback = default_effect_context()
    assert fallback is not outer.capability_effects
    assert fallback is not inner.capability_effects
    assert default_effect_context() is fallback


def test_explicit_bind_reset_clears_published_contexts_and_fallback() -> None:
    previous_fallback = default_effect_context()
    outer, inner = new_effect_context(), new_effect_context()
    configure_default_effect_context(outer)
    configure_default_effect_context(inner)
    assert default_effect_context() is inner

    default_effect_context.cache_clear()

    fallback = default_effect_context()
    assert all(fallback is not context for context in (outer, inner, previous_fallback))
    release_default_effect_context(inner)
    release_default_effect_context(outer)
    assert default_effect_context() is fallback


def test_republishing_does_not_leave_a_stale_duplicate() -> None:
    outer, inner = new_effect_context(), new_effect_context()
    configure_default_effect_context(outer)
    configure_default_effect_context(inner)
    configure_default_effect_context(outer)
    assert default_effect_context() is outer
    release_default_effect_context(outer)
    assert default_effect_context() is inner


async def test_failed_startup_keeps_the_live_outer_container_as_default() -> None:
    """#1856: a failed Container construction must not replace the default.

    Prior state (1): an existing live outer Container is published. The
    failing construction reaches the real bootstrap rejection and raises; the
    exact object that was the default before the attempt must still be the
    default after it, and the outer Container must keep working.
    """
    outer = await create_container(AgentConfig(router_api_key="test-key", database_url="memory://"))
    try:
        before = default_effect_context()
        assert before is outer.capability_effects

        with pytest.raises(ConfigError):
            await create_container(_failing_config())

        assert default_effect_context() is before
        # The surviving default still serves its consumers.
        binding = Binding(
            binding_id="survivor",
            workspace_id="workspace",
            project_id="project",
            capability="jira.search",
        )
        await before.bindings.put(binding)
        assert await before.bindings.get(binding.binding_id) == binding
    finally:
        await outer.aclose()


async def test_failed_startup_keeps_the_cached_fallback_default() -> None:
    """Prior state (2): no live Container, only the cached fallback.

    The failed construction must leave that exact fallback object as the
    default -- neither replaced by the failed candidate nor invalidated.
    """
    fallback = default_effect_context()

    with pytest.raises(ConfigError):
        await create_container(_failing_config())

    assert default_effect_context() is fallback


async def test_failed_startup_keeps_the_previous_quota_tracker_default(
    tmp_path: Path,
) -> None:
    """The process-default quota ledger publication is late, like the context's.

    A SQLite-backed startup that fails at the model-binding bootstrap (the
    real ConfigError) closes its connections in the cleanup handler -- so a
    tracker published before that failure would be a closed-connection
    tracker left as the process default, displacing a live outer container's
    ledger and silently dropping the conductor's fallback evidence. Both
    prior states are asserted: a registered outer tracker survives, and with
    none registered the default stays unset.
    """
    outer = await create_container(AgentConfig(router_api_key="test-key", database_url="memory://"))
    try:
        outer_tracker = get_default_quota_tracker()
        assert outer_tracker is outer.quota_tracker

        with pytest.raises(ConfigError):
            await create_container(_failing_config(f"sqlite:///{tmp_path / 'failed.db'}"))

        assert get_default_quota_tracker() is outer_tracker
    finally:
        await outer.aclose()

    set_default_quota_tracker(None)
    with pytest.raises(ConfigError):
        await create_container(_failing_config(f"sqlite:///{tmp_path / 'failed2.db'}"))
    assert get_default_quota_tracker() is None


async def test_retry_after_a_failed_startup_publishes_the_new_context() -> None:
    """A failed attempt must not poison the next successful one.

    Publication happens after the Container is constructed, so a retry that
    constructs cleanly publishes its own context -- and the previously cached
    fallback is retired by that publication, not by the failure.
    """
    fallback = default_effect_context()

    with pytest.raises(ConfigError):
        await create_container(_failing_config())

    assert default_effect_context() is fallback
    retry = await create_container(AgentConfig(router_api_key="test-key", database_url="memory://"))
    try:
        assert default_effect_context() is retry.capability_effects
        assert default_effect_context() is not fallback
    finally:
        await retry.aclose()


async def test_failed_startup_does_not_mutate_an_injected_effect_context() -> None:
    """A caller-owned context handed in for wiring stays untouched by failure.

    The real bootstrap rejection fires before any Binding is written, so the
    injected authority must hold nothing afterward -- and an injected context
    is published only by a successful construction, never by the attempt.
    """
    injected = new_effect_context()

    with pytest.raises(ConfigError):
        await create_container(_failing_config(), effect_context=injected)

    assert await injected.bindings.get("bad") is None
    assert default_effect_context() is not injected


async def test_failed_startup_closes_the_sqlite_connections_it_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1856: startup cleanup must close what a failed startup opened.

    The recording wrapper delegates to the real `_wire_sqlite_backend` (only
    observing the handles it returns); the failure is the real bootstrap
    rejection. After it, all four connections the attempt opened must be
    closed -- before the fix they leaked, since `aclose` is only reachable
    through a Container that was never returned.
    """
    opened: list[Any] = []
    real_wire = container_module._wire_sqlite_backend

    async def recording(database_url: str, *, exposure_mode: Any) -> tuple[Any, ...]:
        wired = await real_wire(database_url, exposure_mode=exposure_mode)
        opened.extend(wired[:4])
        return wired

    monkeypatch.setattr(container_module, "_wire_sqlite_backend", recording)

    with pytest.raises(ConfigError):
        await create_container(_failing_config(f"sqlite:///{tmp_path / 'failed.db'}"))

    assert len(opened) == 4
    for connection in opened:
        with pytest.raises((ValueError, sqlite3.ProgrammingError)):
            await connection.execute("SELECT 1")


async def test_failed_startup_leaves_an_existing_container_sqlite_resources_open(
    tmp_path: Path,
) -> None:
    """Cleanup takes only the failed attempt's resources, never a live peer's.

    The outer Container owns four connections on its own database file. A
    failed construction on a different file must close its own and leave the
    outer Container's connections serving.
    """
    outer = await create_container(
        AgentConfig(router_api_key="test-key", database_url=f"sqlite:///{tmp_path / 'outer.db'}")
    )
    try:
        outer_connections = (
            outer.db_pool,
            outer.session_conn,
            outer.schedule_conn,
            outer.history_conn,
        )

        with pytest.raises(ConfigError):
            await create_container(_failing_config(f"sqlite:///{tmp_path / 'failed.db'}"))

        assert default_effect_context() is outer.capability_effects
        for connection in outer_connections:
            await connection.execute("SELECT 1")
    finally:
        await outer.aclose()


@requires_postgres
@pytest.mark.usefixtures("_clean_pg_pool_registry")
async def test_failed_startup_releases_the_pg_pool_it_opened() -> None:
    """A pool this failed attempt opened through the registry is released.

    Before the fix the pool stayed registered holding connections to a
    database the operator is about to reconfigure -- the retry would find the
    registry still handing it out.
    """
    before = pool_count()

    with pytest.raises(ConfigError):
        await create_container(_failing_config(postgres_dsn()))

    assert pool_count() == before


@requires_postgres
@pytest.mark.usefixtures("_clean_pg_pool_registry")
async def test_failed_startup_leaves_a_supplied_pg_pool_open() -> None:
    """A pool the caller supplied is the caller's, failure or not.

    The failed attempt must neither release nor close it: after the
    ConfigError the caller's handle still serves, and the registry still
    counts the caller as its one user.
    """
    supplied = await get_pool(postgres_dsn())

    with pytest.raises(ConfigError):
        await create_container(_failing_config(postgres_dsn()), pg_pool=supplied)

    assert await supplied.fetchval("SELECT 1") == 1
    # The test's own hold is the only one left, so this closes it for real.
    assert await release_pool(supplied) is True


async def test_cache_clear_drops_a_published_sqlite_context_after_connection_close(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        router_api_key="test-key", database_url=f"sqlite:///{tmp_path / 'effects.db'}"
    )
    container = await create_container(config)
    try:
        assert default_effect_context() is container.capability_effects
        # Match legacy restart cleanup: callers may close the underlying
        # database directly before explicitly resetting the process default.
        await container.db_pool.close()
        default_effect_context.cache_clear()
        replacement = default_effect_context()
        assert replacement is not container.capability_effects
        binding = Binding(
            binding_id="after-reset",
            workspace_id="workspace",
            project_id="project",
            capability="jira.search",
        )
        await replacement.bindings.put(binding)
        assert await replacement.bindings.get(binding.binding_id) == binding
    finally:
        await container.aclose()
