from __future__ import annotations

import pytest

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY
from maistro.types.config import AgentConfig, ModelBindingConfig


@pytest.mark.asyncio
async def test_bootstrap_loads_only_explicit_model_bindings() -> None:
    effects = new_in_memory_effect_context()
    config = AgentConfig(
        workspace_id="ws-1",
        model_bindings=[
            ModelBindingConfig(
                binding_id="model-binding",
                project_id="project-1",
                provider_name="model-v1",
            )
        ],
    )

    loaded = await bootstrap_model_bindings(config, effects)

    assert [binding.binding_id for binding in loaded] == ["model-binding"]
    resolved = await effects.bindings.resolve(
        "model-binding",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability=MODEL_CHAT_CAPABILITY,
    )
    assert resolved.provider_name == "model-v1"
    assert await effects.bindings.get("not-declared") is None
