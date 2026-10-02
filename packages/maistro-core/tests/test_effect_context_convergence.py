"""Workspace cutover P0.5: backend-selected effect context (#804 / prerequisite A).

The Container must select durable Binding, Invocation and Event stores on
``sqlite:`` and ``postgresql://``, ephemeral stores on ``memory://``, wire an
ApprovalStore on durable backends, expose one Invocation authority (the same
store the Container hands out), and make ``default_effect_context()`` the
Container's ``capability_effects`` — not a second ``lru_cache``d instance.

Each case that fails today is listed in ``KNOWN_GAPS`` with the owning issue.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from maistro.capabilities.approval_store import (
    InMemoryApprovalStore,
    SqliteApprovalStore,
)
from maistro.capabilities.binding_store import InMemoryBindingStore, SqliteBindingStore
from maistro.capabilities.effect_context import default_effect_context
from maistro.capabilities.invocation import InMemoryInvocationStore
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.container import create_container
from maistro.events.envelope import InMemoryEventStore, SqliteEventStore
from maistro.events.invocations import SqliteInvocationStore as EventsSqliteInvocationStore
from maistro.types.config import AgentConfig

from .persistence.conftest import postgres_dsn

KNOWN_GAPS: frozenset[str] = frozenset(
    {
        # #804: registry-constructed nodes still call the process-wide singleton.
        "default_effect_context_is_container",
        # #804 / #1133: GovernedInvocationExecutionService._approvals stays None.
        "approval_store_wired",
        # #804: capability_effects and container.invocation_store are two instances.
        "single_invocation_authority",
    }
)

requires_postgres = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


def test_known_gaps_name_real_cases() -> None:
    cases = {
        "default_effect_context_is_container",
        "approval_store_wired",
        "single_invocation_authority",
    }
    assert cases >= KNOWN_GAPS


@pytest.fixture(autouse=True)
def _clear_default_effect_context_cache() -> None:
    default_effect_context.cache_clear()
    yield
    default_effect_context.cache_clear()


async def _container(**overrides: object):
    return await create_container(AgentConfig(router_api_key="test-key", **overrides))  # type: ignore[arg-type]


async def test_memory_url_selects_ephemeral_effect_stores() -> None:
    container = await _container(database_url="memory://")
    try:
        effects = container.capability_effects
        assert isinstance(effects.bindings, InMemoryBindingStore)
        assert isinstance(effects.invocation_store, InMemoryInvocationStore)
        assert isinstance(effects.event_store, InMemoryEventStore)
    finally:
        await container.aclose()


async def test_sqlite_url_selects_durable_effect_stores() -> None:
    db_path = Path(tempfile.mkdtemp()) / "effect-context.db"
    container = await _container(database_url=f"sqlite:///{db_path}")
    try:
        effects = container.capability_effects
        assert isinstance(effects.bindings, SqliteBindingStore)
        assert isinstance(effects.invocation_store, SqliteInvocationStore)
        assert isinstance(effects.event_store, SqliteEventStore)
    finally:
        await container.aclose()


@requires_postgres
async def test_postgres_url_selects_durable_effect_stores() -> None:
    from maistro.capabilities.binding_store import PgBindingStore
    from maistro.capabilities.pg_invocation_store import PgInvocationStore
    from maistro.events.pg_envelope import PgEventStore

    container = await _container(database_url=postgres_dsn())
    try:
        effects = container.capability_effects
        assert isinstance(effects.bindings, PgBindingStore)
        assert isinstance(effects.invocation_store, PgInvocationStore)
        assert isinstance(effects.event_store, PgEventStore)
    finally:
        await container.aclose()


async def test_default_effect_context_is_the_container_instance() -> None:
    container = await _container(database_url="memory://")
    try:
        same = default_effect_context() is container.capability_effects
        if "default_effect_context_is_container" in KNOWN_GAPS:
            assert not same, "default_effect_context() is the container now; delete the gap"
        else:
            assert same
    finally:
        await container.aclose()


async def test_governed_invocations_use_a_durable_approval_store_on_sqlite() -> None:
    db_path = Path(tempfile.mkdtemp()) / "approval-context.db"
    container = await _container(database_url=f"sqlite:///{db_path}")
    try:
        approvals = container.capability_effects.invocations._approvals
        if "approval_store_wired" in KNOWN_GAPS:
            assert approvals is None, "approval store is wired now; delete the gap"
        else:
            assert isinstance(approvals, (SqliteApprovalStore, InMemoryApprovalStore))
    finally:
        await container.aclose()


async def test_capability_effects_and_container_share_one_invocation_store() -> None:
    db_path = Path(tempfile.mkdtemp()) / "invocation-context.db"
    container = await _container(database_url=f"sqlite:///{db_path}")
    try:
        shared = container.capability_effects.invocation_store is container.invocation_store
        if "single_invocation_authority" in KNOWN_GAPS:
            assert not shared, "invocation authority is unified now; delete the gap"
            assert isinstance(container.capability_effects.invocation_store, SqliteInvocationStore)
            assert isinstance(container.invocation_store, EventsSqliteInvocationStore)
        else:
            assert shared
    finally:
        await container.aclose()
