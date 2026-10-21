"""Governed design explore (director) — pack Graph nodes on canonical execution.

The explore wave is not a Studio button with its own client and not a private
director LLM (M7-A11, #987). It is two node kinds on one canonical
Goal -> Graph -> Run -> NodeRun -> Attempt spine:

- ``design.explore`` — the wave coordinator. It owns the wave parameters
  (Goal revision, Rubric revision, policy, redirect, rejected theses) and
  proves an authorized ``model.chat`` Binding exists *before* anything runs.
  Missing/unauthorized authorization fails the node closed: no synthetic
  theses, no fixture wave, no success-shaped output for work that never
  happened.

- ``design.thesis``  — one thesis slot. Each slot performs exactly one governed
  model call through :class:`ModelChatEgress`, so its NodeRun's physical
  Attempt correlates to one canonical Invocation
  (Capability -> Provider -> Binding -> Invocation, ADR-081226-6b46) and the
  thesis output names that Invocation id.

Width is a graph-synthesis parameter: a width=N wave is a Graph with N
``design.thesis`` nodes behind the coordinator. That is what lets every thesis
land as a real NodeRun/Attempt on the Run — the canonical Run stores refuse
NodeRuns whose node_id is not in the admitted Graph snapshot, so a wave that
invented slots at runtime would be an integrity error, not a feature.

ADR-061 is preserved by construction: ``DesignEngine`` appears nowhere here.
The engine still assembles prompt stacks; the Graph executes them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, Field

from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from maistro.graph.nodes import register_node
from maistro.graph.nodes.base import BaseNode, NodeContext, ReplaySemantics, replay_effect_key
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro_design.governance import (
    build_model_egress,
    extract_json_payload,
    gateway_endpoint_from_env,
    resolve_design_binding,
    scan_model_text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter

EXPLORE_NODE_KIND = "design.explore"
THESIS_NODE_KIND = "design.thesis"

_DEFAULT_ARTIFACT_KIND = "design.thesis"
_MAX_WIDTH = 8


class DesignExploreIn(BaseModel):
    """Wave-level inputs. Prompt inputs are the Goal and Rubric revisions the
    wave explores against, plus policy narrowing — never a raw provider host
    or key.

    The revisions are the canonical ones (``goal_id`` + integer
    ``goal_revision``, ``rubric_id`` + integer ``rubric_revision``), so the
    theses this wave produces can be judged against exactly the Goal and
    Rubric revision the Run was admitted for — and the judge's ``#792`` eval
    rows can name them. Each wave also carries the immutable *content*
    snapshots for those exact revisions (``goal_desired_state``,
    ``goal_success_conditions``, ``rubric_criteria``): revision numbers alone
    would make two unrelated Goals with the same revision number produce
    identical prompts, so the thesis slots must receive what they are
    actually exploring toward and against.
    """

    goal_id: str = Field(description="Canonical Goal identity this wave explores against")
    goal_revision: int = Field(ge=1, description="Goal revision this wave explores against")
    rubric_id: str = Field(description="Canonical Rubric identity theses will be judged against")
    rubric_revision: int = Field(ge=1, description="Rubric revision theses will be judged against")
    #: Immutable content snapshots of the exact revisions named above, so the
    #: thesis prompt carries the Goal and Rubric themselves, not just pointers
    #: to them. Callers resolve them before admitting the wave (e.g. the Goal
    #: revision chain and ``RubricStore.get_revision``); the nodes never
    #: re-resolve, so a prompt cannot silently drift to a newer revision.
    goal_desired_state: str = Field(
        min_length=1,
        description="desired_state of the exact Goal revision this wave explores toward (immutable snapshot)",
    )
    goal_success_conditions: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Success conditions of that Goal revision (immutable snapshot)",
    )
    rubric_criteria: str = Field(
        min_length=1,
        description="Rendered immutable criteria of the exact Rubric revision: dimensions, weights, methods, gate",
    )
    width: int = Field(
        default=2,
        ge=1,
        le=_MAX_WIDTH,
        description="Declared thesis slots in this wave (graph synthesis parameter)",
    )
    exploration_policy: str = Field(
        default="diverse",
        description="Exploration policy name (e.g. diverse | adjacent | adversarial)",
    )
    redirect: str = Field(
        default="",
        description="Optional operator redirect steering this wave",
    )
    rejected_theses: list[str] = Field(
        default_factory=list,
        description="Thesis summaries already rejected, which the wave must avoid repeating",
    )
    artifact_kind: str = Field(
        default=_DEFAULT_ARTIFACT_KIND,
        description="Pack artifact kind every thesis payload must match",
    )
    binding_id: str = Field(
        default="",
        description="Pre-authorized model.chat Binding for this workspace/project",
    )
    model: str = Field(
        default="",
        description="Optional model alias; a Binding pin outranks it",
    )
    timeout_s: float = Field(default=60.0, ge=1.0, le=600.0)


class DesignExploreOut(BaseModel):
    """Wave envelope fanned out to every ``design.thesis`` slot downstream."""

    width: int
    goal_id: str
    goal_revision: int
    rubric_id: str
    rubric_revision: int
    goal_desired_state: str
    goal_success_conditions: tuple[str, ...]
    rubric_criteria: str
    exploration_policy: str
    redirect: str
    rejected_theses: list[str]
    artifact_kind: str
    binding_id: str
    model: str
    timeout_s: float
    #: Echoed so downstream slots and operators can see the authorization that
    #: admitted this wave (the Binding snapshot id, not a secret). Read by the
    #: core replay-conformance test, outside vulture's src-only scan, so it
    #: carries the repo's declarative-field noqa instead of a two-merge
    #: ledger grant this branch cannot land.
    authorized_binding_id: str  # noqa: V107


@register_node
class DesignExploreNode(BaseNode[DesignExploreIn, DesignExploreOut]):
    """Validate authorization for one explore wave and fan out its inputs.

    Makes no model call itself: the wave's Invocations belong to the thesis
    slots, so every thesis NodeRun carries its own Invocation provenance.
    """

    kind: ClassVar[str] = EXPLORE_NODE_KIND
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = DesignExploreIn
    output_schema: ClassVar[type[BaseModel]] = DesignExploreOut
    cost_hint: ClassVar[float] = 0.5
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.IDEMPOTENT
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Design: explore wave"
    description: ClassVar[str] = (
        "Explore-wave coordinator: validates the model.chat Binding for this "
        "workspace/project and fans wave inputs to design.thesis slots. "
        "Fails closed without an authorized Binding."
    )
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "registry": "provider_registry",
        "router": "llm_router",
    }

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        registry: LLMProviderRegistry | None = None,
        router: LLMRouter | None = None,
    ) -> None:
        # Same wiring pattern as llm.summarize (#55/#1079): the container's own
        # effect context resolves Bindings; the bare default authorizes nothing.
        self._effects = effect_context or _default_effects()
        self._registry: LLMProviderRegistry = (
            registry if registry is not None else InMemoryProviderRegistry()
        )
        self._router: LLMRouter = router if router is not None else CostAwareRouter(self._registry)

    async def _execute(self, inputs: DesignExploreIn, ctx: NodeContext) -> DesignExploreOut:
        binding = await resolve_design_binding(self._effects, binding_id=inputs.binding_id, ctx=ctx)
        return DesignExploreOut(
            width=inputs.width,
            goal_id=inputs.goal_id,
            goal_revision=inputs.goal_revision,
            rubric_id=inputs.rubric_id,
            rubric_revision=inputs.rubric_revision,
            goal_desired_state=inputs.goal_desired_state,
            goal_success_conditions=tuple(inputs.goal_success_conditions),
            rubric_criteria=inputs.rubric_criteria,
            exploration_policy=inputs.exploration_policy,
            redirect=inputs.redirect,
            rejected_theses=list(inputs.rejected_theses),
            artifact_kind=inputs.artifact_kind,
            binding_id=inputs.binding_id,
            model=inputs.model,
            timeout_s=inputs.timeout_s,
            authorized_binding_id=binding.binding_id,
        )


class DesignThesisIn(BaseModel):
    """One thesis slot's inputs: wave envelope fields fanned in from the
    coordinator plus this slot's position (``thesis_index`` from its Graph
    node parameters).

    The canonical revision fields carry the same constraints as
    :class:`DesignExploreIn` and are required, not defaulted: ``design.thesis``
    is a registered production node kind, so a graph that reaches a slot with
    incomplete fan-in must fail validation before any authorized model call,
    never produce a success-shaped thesis untied to the revisions the Run was
    admitted for. The immutable content snapshots (``goal_desired_state``,
    ``goal_success_conditions``, ``rubric_criteria``) ride the same fan-out:
    a slot prompt must name the Goal and Rubric themselves, because revision
    numbers alone cannot distinguish two unrelated Goals admitted at the
    same revision number.
    """

    goal_id: str = Field(description="Canonical Goal identity this wave explores against")
    goal_revision: int = Field(ge=1, description="Goal revision this wave explores against")
    rubric_id: str = Field(description="Canonical Rubric identity theses will be judged against")
    rubric_revision: int = Field(ge=1, description="Rubric revision theses will be judged against")
    goal_desired_state: str = Field(
        min_length=1,
        description="desired_state of the exact Goal revision (immutable snapshot)",
    )
    goal_success_conditions: tuple[str, ...] = Field(default_factory=tuple)
    rubric_criteria: str = Field(
        min_length=1,
        description="Rendered immutable criteria of the exact Rubric revision",
    )
    exploration_policy: str = "diverse"
    redirect: str = ""
    rejected_theses: list[str] = Field(default_factory=list)
    artifact_kind: str = _DEFAULT_ARTIFACT_KIND
    binding_id: str = ""
    model: str = ""
    timeout_s: float = Field(default=60.0, ge=1.0, le=600.0)
    thesis_index: int = Field(default=0, ge=0)
    width: int = Field(default=1, ge=1, le=_MAX_WIDTH)


class DesignThesisOut(BaseModel):
    """One thesis payload plus the Invocation that produced it."""

    thesis_id: str  # noqa: V107
    thesis_index: int
    artifact_kind: str
    title: str
    summary: str
    body: str
    invocation_id: str = Field(description="Canonical Invocation id of the model call")
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0


_EXPLORE_SYSTEM_PROMPT = (
    "You are the design explore director for one thesis slot of a design pack. "
    "Produce exactly one thesis payload as a strict JSON object with keys "
    '"title" (string), "summary" (string), and "body" (string). '
    "No prose outside the JSON object."
)


@register_node
class DesignThesisNode(BaseNode[DesignThesisIn, DesignThesisOut]):
    """One governed model call producing one thesis payload.

    Binding resolution happens before prompt assembly, Warden scans the inbound
    payload before it becomes a thesis, and the Invocation id is part of the
    output — a thesis without Invocation provenance cannot exist on this path.
    """

    kind: ClassVar[str] = THESIS_NODE_KIND
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = DesignThesisIn
    output_schema: ClassVar[type[BaseModel]] = DesignThesisOut
    cost_hint: ClassVar[float] = 3.0
    # Retry-safe through the Invocation ledger: a re-entry with the same
    # logical effect key dedupes against the completed Invocation instead of
    # double-charging the wave.
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Design: thesis slot"
    description: ClassVar[str] = (
        "One explore thesis via one governed model Invocation. Warden-scanned; "
        "fails closed without an authorized Binding; never substitutes a "
        "canned thesis."
    )
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "registry": "provider_registry",
        "router": "llm_router",
    }

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        registry: LLMProviderRegistry | None = None,
        router: LLMRouter | None = None,
    ) -> None:
        self._effects = effect_context or _default_effects()
        self._registry: LLMProviderRegistry = (
            registry if registry is not None else InMemoryProviderRegistry()
        )
        self._router: LLMRouter = router if router is not None else CostAwareRouter(self._registry)

    def logical_effect_key(self, inputs: DesignThesisIn, ctx: NodeContext) -> str:
        """This slot's stable logical effect identity across physical retries.

        The slot declares ``EFFECT_KEY`` replay semantics, so a graph retry
        must reconcile with the Invocation the first Attempt recorded instead
        of dispatching a second model call. That reconciliation hangs on this
        key: without it the nested Invocation falls back to its per-NodeRun
        scope, and a retry that re-enters the node under a fresh NodeRun looks
        like brand new work (#1194).
        """

        return replay_effect_key(ctx, f"{THESIS_NODE_KIND}.slot", inputs.model_dump(mode="json"))

    async def _execute(self, inputs: DesignThesisIn, ctx: NodeContext) -> DesignThesisOut:
        binding = await resolve_design_binding(self._effects, binding_id=inputs.binding_id, ctx=ctx)

        request = ModelChatRequest(
            model=inputs.model,
            messages=[
                {"role": "system", "content": _EXPLORE_SYSTEM_PROMPT},
                {"role": "user", "content": _thesis_prompt(inputs)},
            ],
            temperature=0.8,
        )
        egress = build_model_egress(
            self._effects,
            registry=self._registry,
            router=self._router,
            endpoint=gateway_endpoint_from_env(inputs.timeout_s),
        )
        result = await egress.complete(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=self.logical_effect_key(inputs, ctx),
            request=request,
            # The Invocation names the actor, exactly like the core governed
            # model node (``llm.summarize``) does: an audit row that cannot
            # say who asked is a weaker record than the canonical one.
            actor_id=str(ctx.user_id or ""),
        )

        raw = str(_choice_text(result.body))
        payload = extract_json_payload(raw, what=f"thesis slot {inputs.thesis_index}")
        # Strict payload contract: a thesis slot is only successful if the
        # model actually returned the required non-empty string fields. A
        # parsed-but-empty object (e.g. ``{}``) must fail the node closed
        # rather than produce a success-shaped thesis with an empty body.
        missing = [
            field
            for field in ("title", "summary", "body")
            if not str(payload.get(field, "") or "").strip()
        ]
        if missing:
            raise ValueError(
                f"thesis slot {inputs.thesis_index}: model payload is missing "
                f"required field(s): {', '.join(missing)}"
            )
        title = str(payload["title"])
        summary = str(payload["summary"])
        body = str(payload["body"])
        await scan_model_text(
            "\n".join((title, summary, body)),
            what=f"thesis slot {inputs.thesis_index}",
        )
        return DesignThesisOut(
            thesis_id=uuid4().hex,
            thesis_index=inputs.thesis_index,
            artifact_kind=inputs.artifact_kind,
            title=title,
            summary=summary,
            body=body,
            invocation_id=result.invocation_id,
            model_used=result.model,
            tokens_in=result.usage.input_units if result.usage else 0,
            tokens_out=result.usage.output_units if result.usage else 0,
        )


def _thesis_prompt(inputs: DesignThesisIn) -> str:
    parts = [
        f"Goal (revision {inputs.goal_revision}): {inputs.goal_desired_state}",
        f"Rubric (revision {inputs.rubric_revision}) the thesis must satisfy: {inputs.rubric_criteria}",
        f"Exploration policy: {inputs.exploration_policy}",
        f"Thesis slot {inputs.thesis_index + 1} of {inputs.width}.",
        f"The thesis payload kind must be: {inputs.artifact_kind}.",
    ]
    if inputs.goal_success_conditions:
        conditions = "\n".join(f"- {item}" for item in inputs.goal_success_conditions)
        parts.insert(1, f"Goal success conditions:\n{conditions}")
    if inputs.redirect.strip():
        parts.append(f"Operator redirect (obey): {inputs.redirect}")
    if inputs.rejected_theses:
        rejected = "\n".join(f"- {item}" for item in inputs.rejected_theses)
        parts.append(f"Do not repeat these rejected theses:\n{rejected}")
    return "\n\n".join(parts)


def _choice_text(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    return str((message or {}).get("content", "") or "")


def _default_effects() -> CapabilityEffectContext:
    # Imported lazily to keep the module import light and mirror llm_summarize.
    from maistro.capabilities.effect_context import default_effect_context

    return default_effect_context()
