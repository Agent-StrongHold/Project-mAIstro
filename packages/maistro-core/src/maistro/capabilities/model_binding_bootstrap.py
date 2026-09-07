"""Bootstrap operator-declared model Bindings into one canonical effect context.

Provider discovery and authorization are deliberately separate. A configured
model becomes selectable only after an explicit Workspace/Project Binding is
loaded here; no Provider registry entry auto-authorizes itself.
"""

from __future__ import annotations

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.types.config import AgentConfig


async def bootstrap_model_bindings(
    config: AgentConfig,
    effects: CapabilityEffectContext,
) -> tuple[Binding, ...]:
    """Load configured ``model.chat`` Bindings into ``effects``.

    The returned immutable snapshots are informational. Authorization lives in
    ``effects.bindings`` and remains fail-closed when ``config.model_bindings``
    is empty. A declaration with no ``workspace_id`` inherits the deployment's
    canonical Workspace; Project scope is always explicit.

    Durable stores may already contain the same Binding from a prior process.
    Preserve that record's ``created_at`` so reloading unchanged operator
    configuration is idempotent while any authority-changing field still trips
    the store's immutability check.
    """

    loaded: list[Binding] = []
    for declared in config.model_bindings:
        existing = await effects.bindings.get(declared.binding_id)
        values = {
            "binding_id": declared.binding_id,
            "workspace_id": declared.workspace_id.strip() or config.workspace_id,
            "project_id": declared.project_id,
            "node_id": declared.node_id,
            "capability": MODEL_CHAT_CAPABILITY,
            "provider_name": declared.provider_name,
            "credential_refs": declared.credential_refs,
            "policy_refs": declared.policy_refs,
        }
        if existing is not None:
            values["created_at"] = existing.created_at
        binding = Binding.model_validate(values)
        loaded.append(await effects.bindings.put(binding))
    return tuple(loaded)


__all__ = ["bootstrap_model_bindings"]