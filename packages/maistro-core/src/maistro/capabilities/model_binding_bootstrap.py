"""Bootstrap operator-declared model Bindings into one canonical effect context.

Provider discovery and authorization are deliberately separate. A configured
model becomes selectable only after an explicit Workspace/Project Binding is
loaded here; no Provider registry entry auto-authorizes itself.
"""

from __future__ import annotations

from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_CHAT_CAPABILITY,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
)
from maistro.credentials.types import CredentialRecord
from maistro.types.config import AgentConfig
from maistro.types.errors import ConfigError


async def bootstrap_model_bindings(
    config: AgentConfig,
    effects: CapabilityEffectContext,
) -> tuple[Binding, ...]:
    """Load configured ``model.chat`` Bindings into ``effects``.

    The returned immutable snapshots are informational. Authorization lives in
    ``effects.bindings`` and remains fail-closed when ``config.model_bindings``
    is empty. A declaration with no ``workspace_id`` inherits the deployment's
    canonical Workspace; Project scope is always explicit.

    ``AgentConfig.litellm_key`` is the deployment's physical gateway secret. It
    is registered in the scoped credential router under one non-secret default
    key id; a Binding with no explicit ``credential_refs`` authorizes exactly
    that id. Explicit refs are preserved unchanged, so configuration can narrow
    or rotate credentials without this bootstrap silently widening authority.

    A Binding that names a *custom* ref -- anything other than the one id this
    bootstrap ever registers -- is refused here rather than loaded (#1079
    Finding 4). Production configuration has no surface to register a
    credential under any other reference id, so letting such a declaration
    through would authorize a Binding that can never acquire a credential:
    every call would reach ``CredentialScopeError`` at runtime instead of a
    clear failure at startup, while the config itself looked like a valid
    narrowing/rotation setup.

    Durable stores may already contain the same Binding from a prior process.
    Preserve that record's ``created_at`` so reloading unchanged operator
    configuration is idempotent while any authority-changing field still trips
    the store's immutability check.
    """

    loaded: list[Binding] = []
    for declared in config.model_bindings:
        workspace_id = declared.workspace_id.strip() or config.workspace_id
        credential_refs = declared.credential_refs
        unregistrable = [
            ref for ref in credential_refs if ref != DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF
        ]
        if unregistrable:
            raise ConfigError(
                f"model Binding {declared.binding_id!r} declares credential_refs="
                f"{credential_refs!r}, but this deployment's bootstrap only ever "
                f"registers a credential under {DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF!r} "
                "(AgentConfig.litellm_key). There is no production configuration surface "
                f"that registers a credential under {unregistrable!r}, so this Binding "
                "would authorize nothing and every call through it would fail at runtime "
                "with CredentialScopeError. Remove credential_refs (or set it to "
                f"({DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF!r},)) to use the deployment's "
                "default gateway credential."
            )
        if config.litellm_key:
            effects.credentials.add(
                workspace_id=workspace_id,
                project_id=declared.project_id,
                record=CredentialRecord(
                    key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
                    provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
                    api_key=config.litellm_key,
                ),
            )
            if not credential_refs:
                credential_refs = (DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,)

        existing = await effects.bindings.get(declared.binding_id)
        values: dict[str, Any] = {
            "binding_id": declared.binding_id,
            "workspace_id": workspace_id,
            "project_id": declared.project_id,
            "node_id": declared.node_id,
            "capability": MODEL_CHAT_CAPABILITY,
            "provider_name": declared.provider_name,
            "disabled": declared.disabled,
            "credential_refs": credential_refs,
            "policy_refs": declared.policy_refs,
        }
        if existing is not None:
            values["created_at"] = existing.created_at
        binding = Binding.model_validate(values)
        loaded.append(await effects.bindings.put(binding))
    return tuple(loaded)


__all__ = ["bootstrap_model_bindings"]
