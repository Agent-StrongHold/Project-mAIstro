"""Container wiring for the extension install service (#953, M9-B2).

The service must be reachable from the composition root, cached per
container, and wired with the fail-closed default loader — so a deployment
without an activation substrate can inspect and decide but can never
improvise code execution at install time.
"""

from __future__ import annotations

import pytest

from maistro.container import Container
from maistro.extensions.service import ExtensionInstallService, UnwiredExtensionLoader
from maistro.extensions.store import InMemoryExtensionStore


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
