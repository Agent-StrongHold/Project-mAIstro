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
        run_store: Any,
    ) -> None:
        self.effects = effects
        self._run_store = run_store
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

        if self._run_store is None:
            raise BindingResolutionError("Canvas visual evaluation has no canonical Run store")

        run = await self._run_store.get_run(str(context["run_id"]))
        node_run = await self._run_store.get_node_run(str(context["node_run_id"]))
        attempt = await self._run_store.get_attempt(str(context["attempt_id"]))
        if run is None or node_run is None or attempt is None:
            raise BindingResolutionError(
                "Canvas visual evaluation requires existing canonical Run, NodeRun, and Attempt"
            )
        if node_run.run_id != run.run_id or attempt.node_run_id != node_run.node_run_id:
            raise BindingResolutionError(
                "Canvas execution context does not form one canonical chain"
            )

        supplied_workspace = str(context.get("workspace_id") or "").strip()
        supplied_project = str(context.get("project_id") or "").strip()
        if supplied_workspace and supplied_workspace != run.workspace_id:
            raise BindingResolutionError("Canvas Workspace does not match the canonical Run")
        if supplied_project and supplied_project != run.project_id:
            raise BindingResolutionError("Canvas Project does not match the canonical Run")

        node_id = str(context.get("node_id") or node_run.node_id)
        if node_id != node_run.node_id:
            raise BindingResolutionError("Canvas node does not match the canonical NodeRun")
        binding = await self.effects.bindings.resolve(
            str(context["binding_id"]),
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            node_id=node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )
        return await self._egress.complete(
            binding=binding,
            run_id=run.run_id,
            node_run_id=node_run.node_run_id,
            attempt_id=attempt.attempt_id,
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
    run_store: Any,
) -> CanvasModelEgress:
    """Compose Canvas against the supplied canonical authorities.

    All canonical authorities come from the application composition root. Canvas
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
        run_store=run_store,
    )


__all__ = ["CanvasModelEgress", "build_canvas_model_egress"]
