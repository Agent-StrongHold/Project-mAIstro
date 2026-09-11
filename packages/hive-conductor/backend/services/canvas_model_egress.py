"""Canvas's adapter onto the canonical governed model egress.

Canvas supplies visual-quality prompt semantics; this module supplies only the
product-to-core adapter. Provider HTTP, Binding resolution, and Invocation
persistence remain owned by ``maistro.capabilities``.
"""

from __future__ import annotations

from collections.abc import Callable
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
from maistro.runs.model import TERMINAL_ATTEMPT_STATUSES, AttemptStatus


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

    @property
    def run_store(self) -> Any:
        """The canonical RunStore supplied by application composition."""
        return self._run_store

    async def _load_execution(self, context: dict[str, str]) -> tuple[Any, Any, Any]:
        if self._run_store is None:
            raise BindingResolutionError("Canvas visual evaluation has no canonical Run store")
        run = await self._run_store.get_run(str(context["run_id"]))
        node_run = await self._run_store.get_node_run(str(context["node_run_id"]))
        attempt = await self._run_store.get_attempt(str(context["attempt_id"]))
        if run is None or node_run is None or attempt is None:
            raise BindingResolutionError(
                "Canvas visual evaluation requires existing canonical Run, NodeRun, and Attempt"
            )
        return run, node_run, attempt

    @staticmethod
    def _validate_execution(context: dict[str, str], run: Any, node_run: Any, attempt: Any) -> str:
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
        return node_id

    async def _fail_attempt(self, attempt_id: str, exc: Exception) -> None:
        current = await self._run_store.get_attempt(attempt_id)
        if current is not None and current.status not in TERMINAL_ATTEMPT_STATUSES:
            await self._run_store.transition_attempt(
                current.attempt_id,
                AttemptStatus.FAILED,
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
            )

    async def complete(
        self,
        *,
        context: dict[str, str],
        request: ModelChatRequest,
        response_validator: Callable[[ModelCallResult], object] | None = None,
    ) -> ModelCallResult:
        """Cross the governed seam using IDs held by the Canvas execution."""
        required = ("binding_id", "run_id", "node_run_id", "attempt_id")
        missing = [name for name in required if not str(context.get(name) or "").strip()]
        if missing:
            raise BindingResolutionError(
                "Canvas visual evaluation requires canonical execution context: "
                + ", ".join(missing)
            )

        run, node_run, attempt = await self._load_execution(context)
        node_id = self._validate_execution(context, run, node_run, attempt)
        if attempt.status in TERMINAL_ATTEMPT_STATUSES:
            raise BindingResolutionError(
                f"Canvas visual evaluation Attempt {attempt.attempt_id!r} is already terminal"
            )
        if attempt.status is AttemptStatus.CREATED:
            attempt = await self._run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.RUNNING,
            )

        try:
            binding = await self.effects.bindings.resolve(
                str(context["binding_id"]),
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                node_id=node_id,
                capability=MODEL_CHAT_CAPABILITY,
            )
            result = await self._egress.complete(
                binding=binding,
                run_id=run.run_id,
                node_run_id=node_run.node_run_id,
                attempt_id=attempt.attempt_id,
                effect_key="canvas.visual_quality.evaluate",
                request=request,
            )
            attempt_result = (
                response_validator(result) if response_validator is not None else result.body
            )
            await self._run_store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.COMPLETED,
                result=attempt_result,
            )
            return result
        except Exception as exc:
            # Provider refusal or Canvas response validation must settle the
            # canonical Attempt instead of returning a score-shaped success.
            await self._fail_attempt(attempt.attempt_id, exc)
            raise


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
