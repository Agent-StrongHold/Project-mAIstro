"""Container holds the canonical CapabilityRegistry (DI composition root, SPEC-184)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from maistro.capabilities import bootstrap as capability_bootstrap
from maistro.capabilities.registry import CapabilityRegistry
from maistro.container import create_container
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore
from maistro.types.config import AgentConfig

# Concrete stores the composition root can build. The documented plugin hook
# (`maistro.capabilities` entry points) must not construct one of these beside
# the single RunStore ``create_container`` wires.
_RUN_STORE_TYPES = (InMemoryRunStore, SqliteRunStore, PgRunStore)


def _count_init(real: Callable[..., None], seen: list[object]) -> Callable[..., None]:
    def __init__(self: object, *args: Any, **kwargs: Any) -> None:
        seen.append(self)
        real(self, *args, **kwargs)

    return __init__


async def test_container_wires_capability_registry() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert isinstance(container.capabilities, CapabilityRegistry)
    # Canonical slots + inbox baseline come for free with every engine.
    assert "inbox" in container.capabilities.installed("approval")
    assert container.capabilities.is_enabled("infra_action") is True


async def test_each_container_gets_its_own_registry() -> None:
    a = await create_container(AgentConfig(router_api_key="k"))
    b = await create_container(AgentConfig(router_api_key="k"))
    assert a.capabilities is not b.capabilities


async def test_capability_entry_point_hook_does_not_construct_a_second_run_store(
    monkeypatch: Any,
) -> None:
    """The ``maistro.capabilities`` hook must not build a second RunStore.

    ``create_container`` wires one canonical ``RunStore``, then loads that hook
    (``default_capability_registry`` sweeps the entry-point group). A factory
    on the hook that constructs another store fails this test.
    """
    constructed: list[object] = []
    hook_loaded = False
    real_bootstrap = capability_bootstrap.default_capability_registry

    def _guarded(*args: object, **kwargs: object) -> CapabilityRegistry:
        nonlocal hook_loaded
        hook_loaded = True
        saved = {cls: cls.__init__ for cls in _RUN_STORE_TYPES}
        for cls, original in saved.items():
            cls.__init__ = _count_init(original, constructed)  # type: ignore[method-assign]
        try:
            return real_bootstrap(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            for cls, original in saved.items():
                cls.__init__ = original  # type: ignore[method-assign]

    monkeypatch.setattr(capability_bootstrap, "default_capability_registry", _guarded)

    container = await create_container(AgentConfig(router_api_key="test-key"))

    assert hook_loaded, "composition root did not load the capability entry-point hook"
    assert isinstance(container.run_store, _RUN_STORE_TYPES)
    assert constructed == [], (
        "capability entry-point hook constructed a RunStore beside "
        f"the container's canonical {type(container.run_store).__name__}: "
        f"{[type(store).__name__ for store in constructed]}"
    )
