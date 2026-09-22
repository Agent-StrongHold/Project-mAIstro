"""Bootstrap operator-declared model Bindings into the effect context.

Provider discovery and authorization are separate concerns. A configured model
becomes selectable only after an explicit Workspace/Project Binding is loaded;
a graph node cannot authorize itself by naming a model or a generated id.
"""

from __future__ import annotations

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.types.config import AgentConfig


async def bootstrap_model_bindings(
    config: AgentConfig, effects: CapabilityEffectContext
) -> tuple[Binding, ...]:
    """Load the operator's explicit ``model.chat`` Bindings into ``effects``."""

    loaded: list[Binding] = []
    for declared in config.model_bindings:
        binding = Binding(
            binding_id=declared.binding_id,
            workspace_id=declared.workspace_id.strip() or config.workspace_id,
            project_id=declared.project_id,
            node_id=declared.node_id,
            capability=MODEL_CHAT_CAPABILITY,
            provider_name=declared.provider_name,
            credential_refs=declared.credential_refs,
            policy_refs=declared.policy_refs,
        )
        loaded.append(await effects.bindings.put(binding))
    return tuple(loaded)


__all__ = ["bootstrap_model_bindings"]
