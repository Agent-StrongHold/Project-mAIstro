"""Container holds the canonical CapabilityRegistry (DI composition root, SPEC-184)."""

from __future__ import annotations

from maistro.capabilities.registry import CapabilityRegistry
from maistro.container import create_container
from maistro.types.config import AgentConfig


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
