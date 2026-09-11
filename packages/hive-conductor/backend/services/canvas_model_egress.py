"""Canvas's adapter onto the canonical governed model egress.

Canvas supplies visual-quality prompt semantics; this module supplies only the
product-to-core adapter. Provider HTTP, Binding resolution, and Invocation
persistence remain owned by ``maistro.capabilities``.
"""

from __future__ import annotations

from typing import Any

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelCallResult,
    ModelChatEgress,
)
from maistro.capabilities.providers.llm_gateway import (
    GatewayEndpoint,
    ModelChatRequest,
)


class CanvasModelEgress:
    """Resolve an authorized Canvas Binding and execute one model Invocation."""

    def __init__(
        self,
        *,
        effects: CapabilityEffectContext,
        registry: Any,
        router: Any,
        endpoint: GatewayEndpoint,
    ) -> None:
        self.effects = effects
        self._egress = ModelChatEgress(
            effects,
            registry=registry,
            router=router,
            endpoint=endpoint,
        )

    async def complete(
        self,
        *,
        context: dict[str, str],
        request: ModelChatRequest,
    ) -> ModelCallResult:
        """Cross the governed seam using IDs held by the Canvas execution."""
        required = (
            "binding_id",
            "workspace_id",
            "project_id",
            "run_id",
            "node_run_id",
            "attempt_id",
        )
        missing = [name for name in required if not str(context.get(name) or "").strip()]
        if missing:
            raise BindingResolutionError(
                "Canvas visual evaluation requires canonical execution context: "
                + ", ".join(missing)
            )

        node_id = str(context.get("node_id") or "canvas.visual_quality")
        binding = await self.effects.bindings.resolve(
            str(context["binding_id"]),
            workspace_id=str(context["workspace_id"]),
            project_id=str(context["project_id"]),
            node_id=node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )
        return await self._egress.complete(
            binding=binding,
            run_id=str(context["run_id"]),
            node_run_id=str(context["node_run_id"]),
            attempt_id=str(context["attempt_id"]),
            # One logical Canvas quality effect; the canonical IDs provide the
            # execution identity and Invocation deduplication boundary.
            effect_key="canvas.visual_quality.evaluate",
            request=request,
        )


def build_canvas_model_egress(
    *,
    settings: Any,
    effects: CapabilityEffectContext,
    registry: Any,
    router: Any,
) -> CanvasModelEgress:
    """Compose Canvas against the supplied canonical authorities.

    All three authorities come from the application composition root. Canvas
    never creates a fallback Binding store, Provider registry, or Invocation
    ledger of its own.
    """
    base_url = str(getattr(settings, "litellm_api_base", None) or "").strip()
    api_key_value = getattr(settings, "litellm_api_key", None)
    if api_key_value is None:
        api_key = ""
    elif hasattr(api_key_value, "get_secret_value"):
        api_key = str(api_key_value.get_secret_value())
    else:
        api_key = str(api_key_value)
    return CanvasModelEgress(
        effects=effects,
        registry=registry,
        router=router,
        endpoint=GatewayEndpoint(base_url=base_url, api_key=api_key),
    )


__all__ = ["CanvasModelEgress", "build_canvas_model_egress"]
