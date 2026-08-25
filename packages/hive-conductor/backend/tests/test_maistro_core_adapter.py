"""Focused coverage for the Hive -> maistro-core composition adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from adapters.maistro_core import MaistroCoreBridge
from config import Settings


@pytest.mark.asyncio
async def test_start_passes_container_prompt_manager_to_agent_factory(monkeypatch):
    """Hive must consume the prompt store selected by the core Container (#122)."""
    selected_prompt_manager = object()
    container = SimpleNamespace(
        prompt_manager=selected_prompt_manager,
        context_builder=object(),
        warden=object(),
        sentinel=object(),
        learning_store=object(),
        learning_extractor=object(),
        outcome_store=object(),
        session_store=object(),
        quota_tracker=object(),
        agents=None,
    )
    captured: dict[str, object] = {}

    async def fake_create_container(config):
        captured["config"] = config
        return container

    async def fake_create_agents(**kwargs):
        captured.update(kwargs)
        return ["wired-agent"]

    monkeypatch.setattr("maistro.container.create_container", fake_create_container)
    monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)
    monkeypatch.setattr("services.secrets.maistro_llm_api_key", lambda _settings: "")

    bridge = MaistroCoreBridge()
    await bridge.start(
        Settings(
            maistro_agents_dir="agents",
            maistro_llm_base_url="http://localhost:4000/v1",
        )
    )

    assert captured["prompt_manager"] is selected_prompt_manager
    assert container.agents == ["wired-agent"]
    assert bridge.container is container
