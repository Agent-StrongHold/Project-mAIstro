"""Container holds the canonical CapabilityRegistry (DI composition root, SPEC-184)."""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import EntryPoint
from typing import Any, ClassVar

import httpx
import pytest

from maistro.capabilities import discovery
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.container import create_container
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore
from maistro.types.config import AgentConfig


def _record_construction(
    original: Callable[..., None], constructed: list[object]
) -> Callable[..., None]:
    def _init(self: object, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        constructed.append(self)

    return _init


async def test_container_wires_capability_registry() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert isinstance(container.capabilities, CapabilityRegistry)
    # Canonical slots + inbox baseline come for free with every engine.
    assert "inbox" in container.capabilities.installed("approval")
    assert container.capabilities.is_enabled("infra_action") is True


async def test_container_bootstraps_the_canonical_model_binding_and_client() -> None:
    container = await create_container(AgentConfig(router_api_key="k", workspace_id="ws-model"))

    assert container.model_chat_client is not None
    assert container.model_chat_egress is not None
    binding = await container.capability_effects.bindings.get(
        container.model_chat_binding.binding_id
    )
    assert binding is not None
    assert binding.workspace_id == "ws-model"
    assert binding.capability == "model.chat"


async def test_container_model_client_records_invocation(
    monkeypatch: Any,
) -> None:
    class _Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {}

        def json(self) -> dict[str, Any]:
            return {
                "model": "container-model-v1",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def post(self, *args: Any, **kwargs: Any) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    container = await create_container(
        AgentConfig(
            router_api_key="k",
            workspace_id="ws-live",
            litellm_url="http://litellm:4000",
            litellm_key="k",
        )
    )

    body = await container.model_chat_client.complete(
        [{"role": "user", "content": "hello"}],
        "container-model",
        metadata={
            "run_id": "run-live",
            "node_run_id": "node-live",
            "attempt_id": "attempt-live",
            "effect_key": "container:model",
        },
    )

    assert body["choices"][0]["message"]["content"] == "ok"
    history = await container.capability_effects.invocation_store.list_effect(
        run_id="run-live",
        node_run_id="node-live",
        binding_id=container.model_chat_binding.binding_id,
        effect_key="container:model",
    )
    assert len(history) == 1
    assert history[0].binding.provider_name == "container-model"
    assert history[0].usage is not None
    assert history[0].usage.input_units == 2


async def test_each_container_gets_its_own_registry() -> None:
    a = await create_container(AgentConfig(router_api_key="k"))
    b = await create_container(AgentConfig(router_api_key="k"))
    assert a.capabilities is not b.capabilities


async def test_capability_entry_point_hook_does_not_construct_a_second_run_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonempty plugin hook shares the container's canonical runtime.

    Exercise real bootstrap, discovery and registration with a representative
    provider. Observe the concrete store constructors instead of replacing
    their behavior; an extra store in entry-point loading or its factory must
    fail even though discovery catches plugin exceptions.
    """
    constructed: list[object] = []
    for store_type in (InMemoryRunStore, SqliteRunStore, PgRunStore):
        monkeypatch.setattr(
            store_type, "__init__", _record_construction(store_type.__init__, constructed)
        )

    calls: list[str] = []
    provider = FakeProvider("plugin_infra", "infra_monitor")

    def _factory() -> FakeProvider:
        calls.append("factory")
        return provider

    class _PluginEntryPoint(EntryPoint):
        def load(self) -> Callable[[], FakeProvider]:
            calls.append("load")
            return _factory

    entry_point = _PluginEntryPoint(
        name=provider.name, value="test_plugin:make_provider", group="maistro.capabilities"
    )

    def _entry_points(*, group: str) -> tuple[EntryPoint, ...]:
        assert group == "maistro.capabilities"
        calls.append("discover")
        return (entry_point,)

    monkeypatch.setattr(discovery, "entry_points", _entry_points)

    container = await create_container(AgentConfig(router_api_key="test-key"))
    try:
        assert calls == ["discover", "load", "factory"]
        registry = container.capabilities
        assert registry.installed(provider.slot) == [provider.name]
        assert registry.provider(provider.slot, provider.name) is provider
        assert registry.active_name(provider.slot) is None
        registry.activate(provider.slot, provider.name)
        assert await registry.resolve(provider.slot) is provider
        registry.set_enabled(provider.slot, False)
        assert await registry.resolve(provider.slot) is None

        assert len(constructed) == 1, (
            "capability entry-point composition constructed a second RunStore: "
            f"{[type(store).__name__ for store in constructed]}"
        )
        assert constructed[0] is container.run_store
    finally:
        await container.aclose()
