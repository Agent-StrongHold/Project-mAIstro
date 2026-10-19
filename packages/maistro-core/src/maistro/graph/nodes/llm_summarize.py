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

Verification-aware execution (epic M4-I) adds two contracts on top:

- **Observation routing** — ``observations`` carries upstream payloads that
  may be text *or* images. Each is classified, routed to the alias configured
  for its modality, and encoded into the content-part shape the routed model
  accepts. An image observation with no ``image_model`` alias refuses loudly
  rather than re-encoding the image as text.
- **Quality self-report** — every completion self-reports a deterministic
  ``quality`` score (``maistro.graph.verification.quality``) through
  ``NodeContext.result_metadata``, which is the input the executor's
  escalation ladder supervises.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelChatEgress,
)
from maistro.capabilities.providers.llm_gateway import (
    GatewayEndpoint,
    ModelChatRequest,
)
from maistro.graph.verification.escalation import (
    ESCALATED_MODEL_CONTEXT_KEY,
    QUALITY_METADATA_KEY,
)
from maistro.graph.verification.quality import summarize_quality
from maistro.graph.verification.routing import (
    ObservationModality,
    ObservationRoute,
    classify_observation,
    encode_observation,
    route_observations,
)
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter

from . import register_node
from .base import BaseNode, NodeContext, ReplaySemantics, replay_effect_key

if TYPE_CHECKING:
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter


def _scoped_effect_key(ctx: NodeContext, inputs: LlmSummarizeIn, supervised_rung: str) -> str:
    """The Run/node-scoped logical key for one governed completion.

    Two ``llm.summarize`` nodes sharing a Binding and model must not file the
    same keyed effect: the durable executor binds this key as the Invocation
    ``effect_scope``, so a model-only key let the second node adopt the
    first's completed summary. Run + graph node identity, an input digest
    (so re-work with new source is new work), and the escalation rung keep
    every distinct completion distinct while retries of one visit reconcile.
    A blank rung (unsupervised visit) and ``inputs.model`` agree by
    construction, so the scope bound at frontier preparation and the key
    passed inside ``_execute`` can never diverge.
    """

    rung = supervised_rung.strip() or inputs.model
    return replay_effect_key(
        ctx,
        "llm.summarize.complete",
        {"rung": rung, "inputs": inputs.model_dump(mode="json")},
    )


class LlmSummarizeIn(BaseModel):
    text: str = Field(
        default="",
        description="Source text to summarize (may be empty when observations carry the payload)",
    )
    style: str = Field(
        default="bullet",
        description="bullet | paragraph | exec_summary | tldr",
    )
    model: str = Field(
        default="gemini-3.1-flash-lite",
        description="Model alias on the LLM gateway",
    )
    observations: list[Any] = Field(
        default_factory=list,
        description=(
            "Upstream observation payloads handed to the model verbatim. Each is "
            "classified text-or-image, routed to the alias configured for its "
            "modality, and encoded as the matching content part."
        ),
    )
    text_model: str = Field(
        default="",
        description="Alias text observations route to; empty means the node's own `model`",
    )
    image_model: str = Field(
        default="",
        description=(
            "Vision-capable alias image observations route to. Required when any "
            "observation routes as an image; the node refuses rather than "
            "re-encoding an image as text."
        ),
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
    # The shipped model path crosses the governed model egress (#56): the
    # Container's effect context is what makes Bindings resolve; the bare
    # default authorizes nothing, which is a refusal rather than a no-op.
    # `registry`/`router` are likewise the Container's own Provider registry
    # and cost-aware router (#1079), so a resolver-built node reads real
    # Provider metadata and routes through the same authorities the rest of
    # production does, rather than each node's bare `InMemoryProviderRegistry`
    # default silently substituting empty state.
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "registry": "provider_registry",
        "router": "llm_router",
    }
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = LlmSummarizeIn
    output_schema: ClassVar[type[BaseModel]] = LlmSummarizeOut
    cost_hint: ClassVar[float] = 3.0  # billable LLM call
    # Retryable under an effect key (epic M4-I): the governed completion
    # already files its Invocation under the stable key
    # ``llm.summarize.complete:{rung}``, so a re-visit is a *new* keyed effect,
    # never a blind replay of an unbilled one. The default visit budget is
    # still one attempt, so nothing changes for graphs that declare neither
    # ``max_attempts`` nor an ``escalation_ladder`` — the semantics only open
    # the door the executor's quality supervision walks through.
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "LLM: summarize"
    description: ClassVar[str] = (
        "One-shot LLM summarization (bullet / paragraph / exec / tldr). "
        "Runs against the configured LLM gateway via the governed model egress. "
        "Routes text/image observations to the alias configured for their "
        "modality and self-reports a deterministic quality score."
    )

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        registry: LLMProviderRegistry | None = None,
        router: LLMRouter | None = None,
    ) -> None:
        # The container passes its own capability_effects so resolver-built
        # nodes resolve the same Binding/Invocation authorities (#55 wiring
        # pattern). Bare registry construction keeps the process default, which
        # registers no Bindings and therefore authorizes nothing.
        self._effects = effect_context or default_effect_context()
        self._registry: LLMProviderRegistry = (
            registry if registry is not None else InMemoryProviderRegistry()
        )
        self._router: LLMRouter = router if router is not None else CostAwareRouter(self._registry)

    def logical_effect_key(self, inputs: LlmSummarizeIn, ctx: NodeContext) -> str | None:
        """The rung-scoped logical key for one governed completion.

        Epic M4-I escalation re-visits a quality shortfall at the next ladder
        rung; the node's Invocation for that re-visit files under a *new*
        keyed effect (``llm.summarize.complete:{rung}``), never a blind
        replay of an unbilled one — so the node-level key is rung-scoped too.
        Within one visit the key is stable, so a lease-loss retry reconciles
        against the same claim. Developing the key from the supervised
        escalation decision (``escalated_model``) keeps the fail-closed
        executor contract (#1194): an EFFECT_KEY node proves replay safety
        with a concrete key, it does not merely label itself retryable.
        """
        supervised_rung = str(ctx.metadata.get(ESCALATED_MODEL_CONTEXT_KEY) or "").strip()
        return _scoped_effect_key(ctx, inputs, supervised_rung)

    async def _execute(self, inputs: LlmSummarizeIn, ctx: NodeContext) -> LlmSummarizeOut:
        # Gateway configuration is read before the Binding is resolved, as it
        # always was: a deployment with no gateway configured should be told
        # that, not told its Binding is missing. Extracting these two steps
        # for the complexity ratchet must not reorder them.
        endpoint = _gateway_endpoint(timeout_s=inputs.timeout_s)
        binding = await self._authorized_binding(inputs, ctx)

        # Verification-aware escalation (epic M4-I): when the executor's
        # supervision withheld a prior visit for missing its quality floor,
        # the re-visit is told which ladder rung to run. The node's own
        # ``model`` input stays the default for every first visit.
        supervised_rung = str(ctx.metadata.get(ESCALATED_MODEL_CONTEXT_KEY) or "").strip()

        # Observation routing (epic M4-I): upstream payloads are classified
        # text-or-image, routed to the alias configured for their modality,
        # and encoded into the content-part shape the routed model accepts.
        # Precedence is explicit: a supervision-chosen rung outranks the
        # modality floor (the ladder is declared by the same graph author who
        # knows the observations' modalities); otherwise an image observation
        # lifts the request to the vision alias, because feeding an image
        # content part to a text-only alias fails at the provider and
        # re-encoding it as text would discard exactly what it carried.
        observations = list(inputs.observations or [])
        routes = _observation_routes(inputs, observations)
        model_alias = _chosen_model_alias(inputs, supervised_rung, routes)
        user_content = _observation_user_content(inputs, observations, routes)
        egress = ModelChatEgress(
            self._effects,
            registry=self._registry,
            router=self._router,
            endpoint=endpoint,
        )
        result = await egress.complete(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=_scoped_effect_key(ctx, inputs, supervised_rung),
            request=ModelChatRequest(
                model=model_alias,
                messages=[
                    {"role": "system", "content": _system_prompt(inputs)},
                    {"role": "user", "content": user_content},
                ],
                temperature=inputs.temperature,
                max_tokens=inputs.max_tokens,
            ),
            actor_id=str(ctx.user_id or ""),
        )
        out = _summarized(result.body, fallback_model=model_alias)

        # Quality self-report (epic M4-I): the deterministic score the
        # executor's escalation ladder supervises. Measured against everything
        # the model was shown as source — the text input plus the text half of
        # any observations — so a summary cannot score well by ignoring the
        # payloads it was handed. Written through the per-visit result-metadata
        # channel; graphs that declare no ladder simply carry it as evidence.
        text_payloads = [
            payload if isinstance(payload, str) else str(payload)
            for payload, route in zip(observations, routes, strict=False)
            if route.modality == ObservationModality.TEXT
        ]
        source_for_quality = "\n\n".join([*text_payloads, inputs.text]).strip()
        ctx.result_metadata[QUALITY_METADATA_KEY] = summarize_quality(
            source_for_quality, out.summary
        )
        return out

    async def _authorized_binding(self, inputs: LlmSummarizeIn, ctx: NodeContext) -> Any:
        """The model.chat Binding this call runs under, refused before any call."""

        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "llm.summarize requires a pre-authorized model.chat binding_id "
                "before any model call"
            )
        return await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )


def _env_first(*names: str) -> str:
    """The first of these environment variables that is set and non-empty."""

    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _gateway_endpoint(*, timeout_s: float) -> GatewayEndpoint:
    """The gateway this node calls, from env; it never hardcodes credentials.

    The maistro config layer already loads these, so reading them here is
    reading configuration, not inventing it. No base URL is a refusal: a node
    that silently called nothing would report an empty summary as a success.
    """

    base_url = _env_first("MAISTRO_LLM_BASE_URL", "LITELLM_URL", "LITELLM_API_BASE").rstrip("/")
    if not base_url:
        raise RuntimeError("llm.summarize: no LLM base URL configured")
    return GatewayEndpoint(
        base_url=base_url,
        api_key=_env_first("MAISTRO_LLM_API_KEY", "LITELLM_API_KEY", "LITELLM_MASTER_KEY"),
        timeout_s=timeout_s,
    )


def _system_prompt(inputs: LlmSummarizeIn) -> str:
    """The style prompt, with the caller's extra instructions appended."""

    prompt = _STYLE_PROMPTS.get(inputs.style, _STYLE_PROMPTS["bullet"])
    if inputs.system_prompt_extra:
        return prompt + "\n\n" + inputs.system_prompt_extra
    return prompt


def _observation_routes(
    inputs: LlmSummarizeIn, observations: list[Any]
) -> tuple[ObservationRoute, ...]:
    """Route the declared observations; an image with no vision alias refuses.

    Re-encoding an image as text would discard exactly what the observation
    carried, so the misconfiguration is refused before any model call.
    """
    if not observations:
        return ()
    image_alias = inputs.image_model.strip()
    has_image = any(
        classify_observation(payload) == ObservationModality.IMAGE for payload in observations
    )
    if has_image and not image_alias:
        raise RuntimeError(
            "llm.summarize received an image observation but no image_model "
            "alias is configured; refusing to re-encode an image as text "
            "(epic M4-I observation routing)"
        )
    return route_observations(
        observations,
        text_model=inputs.text_model.strip() or inputs.model,
        image_model=image_alias or inputs.model,
    )


def _chosen_model_alias(
    inputs: LlmSummarizeIn,
    supervised_rung: str,
    routes: tuple[ObservationRoute, ...],
) -> str:
    """The alias this completion runs on: the supervised rung, else the modality floor."""
    if supervised_rung:
        return supervised_rung
    if any(route.modality == ObservationModality.IMAGE for route in routes):
        return inputs.image_model.strip()
    return inputs.model


def _observation_user_content(
    inputs: LlmSummarizeIn,
    observations: list[Any],
    routes: tuple[ObservationRoute, ...],
) -> str | list[dict[str, Any]]:
    """Observations as content parts (plus the text input, when it speaks too)."""
    if not observations:
        return inputs.text
    content_parts: list[dict[str, Any]] = [
        encode_observation(payload, route)
        for payload, route in zip(observations, routes, strict=False)
    ]
    if inputs.text.strip():
        content_parts.append({"type": "text", "text": inputs.text})
    return content_parts


def _summarized(data: dict[str, Any], *, fallback_model: str) -> LlmSummarizeOut:
    """Read the gateway's response shape into this node's output."""

    text = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
    usage = data.get("usage", {}) or {}
    return LlmSummarizeOut(
        summary=text.strip(),
        model_used=str(data.get("model") or fallback_model),
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
    )
