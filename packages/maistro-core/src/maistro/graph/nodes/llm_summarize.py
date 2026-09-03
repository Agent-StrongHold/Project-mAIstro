"""`llm.summarize` — single-shot LLM summarization through the governed egress.

The node no longer performs HTTP itself: it resolves a pre-authorized
Workspace/Project-scoped Binding and crosses the canonical Provider/Binding/
Invocation boundary (#56), so every summarize call persists an Invocation with
model/version/token/cost/provider metadata. The base URL + API key still come
from the runtime environment (maistro config) — not from the DAG definition —
so user-saved DAGs remain portable across environments.

Model selection keeps its existing semantics: the node's ``model`` alias is
honored as the requested model, and a Binding that pins ``provider_name``
outranks it.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelChatEgress,
    ModelChatRequest,
)
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter

from . import register_node
from .base import BaseNode, NodeContext


class LlmSummarizeIn(BaseModel):
    text: str = Field(description="Source text to summarize")
    style: str = Field(
        default="bullet",
        description="bullet | paragraph | exec_summary | tldr",
    )
    model: str = Field(
        default="gemini-3.1-flash-lite",
        description="Model alias on the LLM gateway",
    )
    max_tokens: int = Field(default=512, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    system_prompt_extra: str = Field(
        default="",
        description="Optional extra system context (e.g. project profile)",
    )
    timeout_s: float = 30.0
    binding_id: str = Field(
        default="",
        description="Pre-authorized model.chat Binding for this node's workspace/project",
    )


class LlmSummarizeOut(BaseModel):
    summary: str
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0


_STYLE_PROMPTS = {
    "bullet": "Summarize the text as a concise bullet list. Use - prefix; one bullet per distinct point.",
    "paragraph": "Summarize the text as a single tight paragraph (3-5 sentences).",
    "exec_summary": (
        "Summarize as an executive summary: a one-line headline, then 3 bullets "
        "of key wins / blockers / next actions."
    ),
    "tldr": "Give a one-sentence TL;DR.",
}


@register_node
class LlmSummarizeNode(BaseNode[LlmSummarizeIn, LlmSummarizeOut]):
    kind: ClassVar[str] = "llm.summarize"
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = LlmSummarizeIn
    output_schema: ClassVar[type[BaseModel]] = LlmSummarizeOut
    cost_hint: ClassVar[float] = 3.0  # billable LLM call
    idempotent: ClassVar[bool] = False  # LLM output varies; not safe to retry blindly
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "LLM: summarize"
    description: ClassVar[str] = (
        "One-shot LLM summarization (bullet / paragraph / exec / tldr). "
        "Runs against the configured LLM gateway via the governed model egress."
    )

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        registry: InMemoryProviderRegistry | None = None,
        router: CostAwareRouter | None = None,
    ) -> None:
        # The container passes its own capability_effects so resolver-built
        # nodes resolve the same Binding/Invocation authorities (#55 wiring
        # pattern). Bare registry construction keeps the process default, which
        # registers no Bindings and therefore authorizes nothing.
        self._effects = effect_context or default_effect_context()
        self._registry = registry if registry is not None else InMemoryProviderRegistry()
        self._router = router if router is not None else CostAwareRouter(self._registry)

    async def _execute(self, inputs: LlmSummarizeIn, ctx: NodeContext) -> LlmSummarizeOut:
        # LLM gateway endpoint + key — pulled from env (maistro config layer
        # already loads these). The node never hardcodes credentials.
        base_url = (
            os.environ.get("MAISTRO_LLM_BASE_URL")
            or os.environ.get("LITELLM_URL")
            or os.environ.get("LITELLM_API_BASE")
            or ""
        ).rstrip("/")
        api_key = (
            os.environ.get("MAISTRO_LLM_API_KEY")
            or os.environ.get("LITELLM_API_KEY")
            or os.environ.get("LITELLM_MASTER_KEY")
            or ""
        )
        if not base_url:
            raise RuntimeError("llm.summarize: no LLM base URL configured")

        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "llm.summarize requires a pre-authorized model.chat binding_id "
                "before any model call"
            )
        binding = await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )

        sys_prompt = _STYLE_PROMPTS.get(inputs.style, _STYLE_PROMPTS["bullet"])
        if inputs.system_prompt_extra:
            sys_prompt = sys_prompt + "\n\n" + inputs.system_prompt_extra

        request = ModelChatRequest(
            model=inputs.model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": inputs.text},
            ],
            temperature=inputs.temperature,
            max_tokens=inputs.max_tokens,
        )
        egress = ModelChatEgress(
            self._effects,
            registry=self._registry,
            router=self._router,
            endpoint=GatewayEndpoint(
                base_url=base_url, api_key=api_key, timeout_s=inputs.timeout_s
            ),
        )
        result = await egress.complete(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=f"llm.summarize.complete:{inputs.model}",
            request=request,
        )

        data: dict[str, Any] = result.body
        text = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
        usage = data.get("usage", {}) or {}
        return LlmSummarizeOut(
            summary=text.strip(),
            model_used=str(data.get("model") or inputs.model),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )
