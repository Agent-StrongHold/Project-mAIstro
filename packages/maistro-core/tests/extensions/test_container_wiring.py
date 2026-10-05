"""Container wiring for the extension install service (#953, M9-B2).

The service must be reachable from the composition root, cached per
container, and wired with the fail-closed default loader — so a deployment
without an activation substrate can inspect and decide but can never
improvise code execution at install time.
"""

from __future__ import annotations

import pytest

from maistro.container import Container
from maistro.extensions.service import UnwiredExtensionLoader
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
