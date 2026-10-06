"""Container wiring for the extension install service (#953, M9-B2).

The service must be reachable from the composition root, cached per
container, and wired with the fail-closed default loader — so a deployment
without an activation substrate can inspect and decide but can never
improvise code execution at install time.
"""

from __future__ import annotations

import pytest

from maistro.container import Container, create_container
from maistro.extensions.health import InMemoryExtensionHealthStore
from maistro.extensions.service import ExtensionInstallService, UnwiredExtensionLoader
from maistro.extensions.sqlite_health_store import SqliteExtensionHealthStore
from maistro.extensions.store import InMemoryExtensionStore
from maistro.types.config import AgentConfig


def _bare_container() -> Container:
    return Container(
        config=None,
        router=None,
        classifier=None,
        quota_tracker=None,
        learning_store=None,
        learning_extractor=None,
        outcome_store=None,
        session_store=None,
        warden=None,
        gate=None,
        sentinel=None,
        context_builder=None,
        intent_registry=None,
    )


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
class TestContainerWiring:
    def test_service_is_lazily_built_and_cached(self) -> None:
        container = _bare_container()
        assert container.extension_install_service is None
        service = container.ensure_extension_install_service()
        assert service is container.ensure_extension_install_service()
        assert container.extension_install_service is service

    def test_default_wiring_uses_in_memory_store_and_unwired_loader(self) -> None:
        container = _bare_container()
        service = container.ensure_extension_install_service()
        assert isinstance(service._store, InMemoryExtensionStore)
        assert isinstance(service._loader, UnwiredExtensionLoader)

    def test_pre_wired_store_is_kept(self) -> None:
        store = InMemoryExtensionStore()
        container = _bare_container()
        container.extension_install_store = store
        service = container.ensure_extension_install_service()
        assert service._store is store

    def test_health_service_shares_the_install_store(self) -> None:
        """The operational-view facade (#978) reads lifecycle evidence from
        the SAME store instance the install service owns — never a copy that
        could drift from the canonical record of activation."""
        container = _bare_container()
        assert container.extension_health_service is None
        install = container.ensure_extension_install_service()
        health = container.ensure_extension_health_service()
        assert health is container.ensure_extension_health_service()
        assert health._install_store is install._store
        assert isinstance(health._install_store, InMemoryExtensionStore)

    def test_pre_wired_service_backfills_store_and_health_reads_it(self) -> None:
        """A host following the documented extension point may prewire the
        install service over its own loader and store without mirroring the
        store onto ``extension_install_store``. The container must
        synchronize the field from the supplied service and project health
        from that service's store — never from a freshly forked empty one
        that would disagree with the canonical install lifecycle."""
        store = InMemoryExtensionStore()
        container = _bare_container()
        prewired = ExtensionInstallService(store, loader=UnwiredExtensionLoader())
        container.extension_install_service = prewired

        assert container.ensure_extension_install_service() is prewired
        assert container.extension_install_store is store

        health = container.ensure_extension_health_service()
        assert health._install_store is store


# --- #978: the composition root selects the health store from the backend ---


async def test_create_container_wires_the_sqlite_health_twin(tmp_path: object) -> None:
    """Health evidence and operator decisions are durable-admission state:
    when the container owns a SQLite connection, ``create_container`` must
    wire the SQLite twin — otherwise an operator quarantine/disable recorded
    through the API would vanish on restart and the held extension would
    flip back to ready on the first health request after one."""
    config = AgentConfig(router_api_key="test-key", database_url=f"sqlite:///{tmp_path}/health.db")
    container = await create_container(config)
    try:
        assert container.db_pool is not None
        assert isinstance(container.extension_health_store, SqliteExtensionHealthStore)
        health = container.ensure_extension_health_service()
        assert health._health_store is container.extension_health_store
    finally:
        await container.aclose()


async def test_ephemeral_container_falls_back_to_in_memory_health_store() -> None:
    """``memory://`` owns no SQLite connection, so the deliberate ephemeral
    configuration gets the in-memory twin — the fallback exists for tests
    and explicitly ephemeral containers, not for deployments with a backend."""
    config = AgentConfig(router_api_key="test-key", database_url="memory://")
    container = await create_container(config)
    try:
        assert isinstance(container.extension_health_store, InMemoryExtensionHealthStore)
    finally:
        await container.aclose()
