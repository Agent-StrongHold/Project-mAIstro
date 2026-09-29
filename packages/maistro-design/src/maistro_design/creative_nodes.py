"""Deterministic node kinds for the creative-production Graph (#775).

The creative Graph planned by :mod:`maistro_design.creative_graph` executes
through the canonical durable executor (``maistro.graph.durable_runs``), so
its nodes are ordinary registered node kinds — no private runtime, no private
scheduler, no model calls. Each stage is a deterministic transform over the
durable outputs its canonical predecessors recorded, which is what makes the
fan-out / targeted-regeneration behaviour testable and replayable end to end.

Two conventions carry the whole graph:

**Relayed shared context.** The durable executor feeds a node exactly the
merged outputs of its selected immediate predecessors (plus its own static
parameters). Downstream stages therefore relay the shared creative context
forward verbatim; no stage re-derives or rewrites it. The context payload is
exactly :meth:`ArtifactProjection.shared_context`'s slice plus the brief's
source references, so every branch of one CreativeBrief version consumes
byte-identical shared decisions.

**Cross-branch records on the blackboard.** Parallel artifact branches emit
outputs under shared keys (same schema), so a fan-in node cannot read sibling
payloads from its merged inputs. Each branch therefore records its durable
artifact record under ``artifact::<request_id>`` in the blackboard's
``node_annotations`` — the executor merges sibling annotation deltas and
persists them in ``GraphExecutionState.blackboard_snapshot``, so the
cross-artifact critique, targeted refinement, acceptance and export stages
read real persisted state, never client-side memory.

Every physical execution of every stage still crosses the canonical
NodeRun/Attempt seams; this module adds no evidence path of its own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.execution_state import thaw_json_value
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.base import KindCategory

__all__ = [
    "ARTIFACT_ANNOTATION_PREFIX",
    "CreativeGenerateInput",
    "SharedContextStageOutput",
    "artifact_annotation_key",
    "shared_context_from_brief",
    "shared_decision_digest",
]


ARTIFACT_ANNOTATION_PREFIX = "artifact::"
"""Blackboard annotation namespace holding one durable record per artifact.

Annotation values are canonical-JSON strings: the blackboard's annotations
are ``dict[str, str]`` and merge per key across parallel siblings, so one
stringified record per branch is what makes the fan-in stages see every
branch's durable artifact record.
"""

_SHARED_CONTEXT_FIELDS: tuple[str, ...] = (
    "workspace_id",
    "project_id",
    "goal_id",
    "goal_revision",
    "goal_owner_agent_id",
    "goal_delegation_ref",
    "brief_lineage_id",
    "brief_id",
    "brief_version",
    "persona_id",
    "persona_version",
    "design_system_slug",
    "design_system_version",
    "audience",
    "beneficiaries",
    "required_messages",
    "cta",
    "required_facts",
    "prohibited_claims",
    "tone_constraints",
    "artifact_requests",
)


def shared_context_from_brief(brief: Any) -> dict[str, Any]:
    """The shared decision payload every branch of one brief version consumes.

    Mirrors the identity/context slice of :class:`maistro_design.brief.CreativeBrief`
    (the same slice :meth:`ArtifactProjection.shared_context` carries), plus the
    delegation reference so graph inspection can name the Agent delegation
    alongside the accountable owner.
    """
    return {
        "workspace_id": brief.workspace_id,
        "project_id": brief.project_id,
        "goal_id": brief.goal_id,
        "goal_revision": brief.goal_revision,
        "goal_owner_agent_id": brief.goal_owner_agent_id,
        "goal_delegation_ref": (
            brief.goal_delegation_ref.model_dump(mode="json")
            if brief.goal_delegation_ref is not None
            else None
        ),
        "brief_lineage_id": brief.lineage_id,
        "brief_id": brief.brief_id,
        "brief_version": brief.version,
        "persona_id": brief.persona_id,
        "persona_version": brief.persona_version,
        "design_system_slug": brief.design_system_slug,
        "design_system_version": brief.design_system_version,
        "audience": brief.audience,
        "beneficiaries": list(brief.beneficiaries),
        "required_messages": list(brief.required_messages),
        "cta": brief.cta,
        "required_facts": [fact.model_dump(mode="json") for fact in brief.required_facts],
        "prohibited_claims": list(brief.prohibited_claims),
        "tone_constraints": list(brief.tone_constraints),
        "artifact_requests": [
            request.model_dump(mode="json") for request in brief.artifact_requests
        ],
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def shared_decision_digest(context: dict[str, Any]) -> str:
    """Stable identity of the shared creative decisions one run consumes.

    Covers exactly the fields whose change must invalidate descendants
    (audience, required messages, CTA, facts, prohibitions, tone, Persona and
    Design System versions); request-specific detail is excluded because it
    belongs to a branch, not to the shared decision.
    """
    selection = {field: context.get(field) for field in _SHARED_CONTEXT_FIELDS}
    selection.pop("artifact_requests")
    return hashlib.sha256(_canonical_json(selection).encode("utf-8")).hexdigest()


def artifact_annotation_key(request_id: str) -> str:
    return f"{ARTIFACT_ANNOTATION_PREFIX}{request_id}"


class _IgnoreExtra(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BriefResolveInput(_IgnoreExtra):
    """Entry stage input: the launch payload records the CreativeBrief."""

    brief: dict[str, Any]


class _SharedRelayIn(_IgnoreExtra):
    shared_context: dict[str, Any]


class SharedContextStageOutput(BaseModel):
    """What every shared upstream stage emits forward, unchanged."""

    shared_context: dict[str, Any]


class BriefResolveOutput(SharedContextStageOutput):
    brief_id: str
    brief_version: int
    goal_id: str
    goal_revision: int


class ResearchEvidenceOutput(SharedContextStageOutput):
    evidence_digest: str
    evidence_count: int


class MessageArchitectureOutput(SharedContextStageOutput):
    message_decision_id: str
    audience: str
    required_messages: list[str]
    cta: str | None


class CopyPlatformOutput(SharedContextStageOutput):
    copy_platform_id: str
    tone_constraints: list[str]


class VisualDirectionOutput(SharedContextStageOutput):
    visual_decision_id: str
    design_system_slug: str
    design_system_version: str | None


class ArtifactPlanOutput(SharedContextStageOutput):
    artifact_plan_id: str
    message_decision_id: str
    visual_decision_id: str
    artifact_requests: list[dict[str, Any]]


class CreativeGenerateInput(_IgnoreExtra):
    """Branch input: the shared decisions plus this branch's request.

    ``shared_context`` and the decision ids are carried by the canonical
    predecessor outputs on the first visit; a canonical retry visit receives
    static inputs only, so they default empty and the node falls back to the
    shared decisions persisted once on the run blackboard.
    """

    shared_context: dict[str, Any] = Field(default_factory=dict)
    message_decision_id: str = ""
    visual_decision_id: str = ""
    request: dict[str, Any] = Field(default_factory=dict)


class ArtifactGenerateOutput(BaseModel):
    request_id: str
    channel: str
    artifact_id: str
    content: str
    content_digest: str
    consumed_message_decision_id: str
    consumed_visual_decision_id: str
    goal_revision: int
    brief_version: int
    shared_context: dict[str, Any]


class CritiqueInput(_IgnoreExtra):
    shared_context: dict[str, Any] = Field(default_factory=dict)


class CrossCritiqueOutput(BaseModel):
    shared_context: dict[str, Any]
    critique_id: str
    artifact_count: int
    shared_decision_consistent: bool
    findings: list[str]


class TargetedRefinementOutput(BaseModel):
    shared_context: dict[str, Any]
    refinement_id: str
    refined_request_ids: list[str]
    unchanged_request_ids: list[str]


class AcceptanceOutput(BaseModel):
    shared_context: dict[str, Any]
    acceptance_id: str
    accepted: bool
    accepted_request_ids: list[str]
    rejections: list[str]


class PublishExportOutput(BaseModel):
    export_id: str
    manifest: list[dict[str, Any]]


def _digest(*parts: Any) -> str:
    return hashlib.sha256(_canonical_json(parts).encode("utf-8")).hexdigest()


def _record_shared_stage(ctx: NodeContext, *, stage: str, decision_id: str) -> None:
    """Persist one shared decision identity once, on the stage that decided it.

    The blackboard is canonical durable run state (it survives in
    ``GraphExecutionState.blackboard_snapshot``), so a decision recorded here
    is referenced by every branch — including a branch's retry visit, whose
    canonical inputs carry static parameters and launch inputs only.
    """
    if ctx.blackboard is None:
        return
    decisions = dict(ctx.blackboard.metadata.get("shared_decisions") or {})
    decisions.setdefault(stage, decision_id)
    ctx.blackboard.metadata["shared_decisions"] = decisions


def _shared_fallback(ctx: NodeContext) -> tuple[dict[str, Any], dict[str, str]]:
    """The persisted shared context and decision ids, for reference by any node.

    Canonical retry visits receive static inputs only (immediate-predecessor
    outputs are not re-selected for a revisit), so every consumer falls back
    to the decisions persisted once on the run blackboard.
    """
    if ctx.blackboard is None:
        return {}, {}
    metadata = dict(ctx.blackboard.metadata or {})
    context = thaw_json_value(metadata.get("shared_context") or {})
    decisions = {str(k): str(v) for k, v in dict(metadata.get("shared_decisions") or {}).items()}
    assert isinstance(context, dict)
    return context, decisions


class CreativeBriefResolve(BaseNode[BriefResolveInput, BriefResolveOutput]):
    """Entry stage: resolve the CreativeBrief into the shared decision context."""

    kind: ClassVar[str] = "creative.brief_resolve"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = BriefResolveInput
    output_schema: ClassVar[type[BaseModel]] = BriefResolveOutput
    display_name: ClassVar[str] = "CreativeBrief resolve"
    description: ClassVar[str] = (
        "Resolves the launch CreativeBrief into the shared creative context every "
        "branch consumes; refuses to plan from a brief missing canonical identity."
    )

    async def _execute(self, inputs: BriefResolveInput, ctx: NodeContext) -> BriefResolveOutput:
        brief = inputs.brief
        for field in ("goal_id", "goal_revision", "brief_id", "brief_version", "workspace_id"):
            if not brief.get(field):
                raise ValueError(f"CreativeBrief launch payload is missing {field!r}")
        context = brief.get("shared_context")
        if not isinstance(context, Mapping) or not context.get("goal_id"):
            raise ValueError("CreativeBrief launch payload is missing shared_context")
        # Launch state arrives frozen (canonical durable state is immutable
        # JSON); re-emit it as ordinary JSON so every downstream stage and
        # NodeResult carries serializable, plain values.
        shared = thaw_json_value(context)
        assert isinstance(shared, dict)  # narrowing for the serializer
        if ctx.blackboard is not None:
            # The shared creative context is persisted exactly once, by the
            # stage that resolves it; every branch references this record.
            ctx.blackboard.metadata["shared_context"] = shared
        return BriefResolveOutput(
            shared_context=shared,
            brief_id=str(brief["brief_id"]),
            brief_version=int(brief["brief_version"]),
            goal_id=str(brief["goal_id"]),
            goal_revision=int(brief["goal_revision"]),
        )


class CreativeResearchEvidence(BaseNode[_SharedRelayIn, ResearchEvidenceOutput]):
    """Evidence stage: anchors the brief's required facts to their sources."""

    kind: ClassVar[str] = "creative.research_evidence"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _SharedRelayIn
    output_schema: ClassVar[type[BaseModel]] = ResearchEvidenceOutput
    display_name: ClassVar[str] = "Research / evidence"
    description: ClassVar[str] = (
        "Collects the brief's required facts and evidence references into one "
        "durable evidence output downstream stages cite."
    )

    async def _execute(self, inputs: _SharedRelayIn, ctx: NodeContext) -> ResearchEvidenceOutput:
        facts = inputs.shared_context.get("required_facts") or []
        output = ResearchEvidenceOutput(
            shared_context=inputs.shared_context,
            evidence_digest=_digest("evidence", facts),
            evidence_count=len(facts),
        )
        _record_shared_stage(ctx, stage="research.evidence", decision_id=output.evidence_digest)
        return output


class CreativeMessageArchitecture(BaseNode[_SharedRelayIn, MessageArchitectureOutput]):
    """Shared message decision: audience, required messages, CTA — decided once."""

    kind: ClassVar[str] = "creative.message_architecture"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _SharedRelayIn
    output_schema: ClassVar[type[BaseModel]] = MessageArchitectureOutput
    display_name: ClassVar[str] = "Message architecture"
    description: ClassVar[str] = (
        "Decides the shared message architecture once and records its identity; "
        "every artifact branch cites this decision instead of re-deriving it."
    )

    async def _execute(self, inputs: _SharedRelayIn, ctx: NodeContext) -> MessageArchitectureOutput:
        context = inputs.shared_context
        decision_id = shared_decision_digest(context)
        output = MessageArchitectureOutput(
            shared_context=context,
            message_decision_id=decision_id,
            audience=str(context.get("audience") or ""),
            required_messages=list(context.get("required_messages") or []),
            cta=context.get("cta"),
        )
        _record_shared_stage(ctx, stage="message.architecture", decision_id=decision_id)
        return output


class CreativeCopyPlatform(BaseNode[_SharedRelayIn, CopyPlatformOutput]):
    """Copy platform decision: where the copy runs and under which constraints."""

    kind: ClassVar[str] = "creative.copy_platform"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _SharedRelayIn
    output_schema: ClassVar[type[BaseModel]] = CopyPlatformOutput
    display_name: ClassVar[str] = "Copy platform"
    description: ClassVar[str] = (
        "Records the copy platform decision (channels in play and the tone "
        "constraints that bind them) as one referenced output."
    )

    async def _execute(self, inputs: _SharedRelayIn, ctx: NodeContext) -> CopyPlatformOutput:
        context = inputs.shared_context
        channels = sorted(
            str(request.get("channel") or "")
            for request in (context.get("artifact_requests") or [])
        )
        tone = list(context.get("tone_constraints") or [])
        output = CopyPlatformOutput(
            shared_context=context,
            copy_platform_id=_digest("copy_platform", channels, tone),
            tone_constraints=tone,
        )
        _record_shared_stage(ctx, stage="copy.platform", decision_id=output.copy_platform_id)
        return output


class CreativeVisualDirection(BaseNode[_SharedRelayIn, VisualDirectionOutput]):
    """Shared visual decision: Design System version plus direction identity."""

    kind: ClassVar[str] = "creative.visual_direction"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _SharedRelayIn
    output_schema: ClassVar[type[BaseModel]] = VisualDirectionOutput
    display_name: ClassVar[str] = "Visual direction"
    description: ClassVar[str] = (
        "Decides the shared visual direction once — the referenced Design "
        "System version plus a direction identity every visual branch cites."
    )

    async def _execute(self, inputs: _SharedRelayIn, ctx: NodeContext) -> VisualDirectionOutput:
        context = inputs.shared_context
        slug = context.get("design_system_slug")
        if not slug:
            raise ValueError("shared context carries no design system reference")
        output = VisualDirectionOutput(
            shared_context=context,
            visual_decision_id=_digest(
                "visual",
                slug,
                context.get("design_system_version"),
                context.get("tone_constraints"),
            ),
            design_system_slug=str(slug),
            design_system_version=context.get("design_system_version"),
        )
        _record_shared_stage(ctx, stage="visual.direction", decision_id=output.visual_decision_id)
        return output


class CreativeArtifactPlan(BaseNode[CreativeGenerateInput, ArtifactPlanOutput]):
    """Artifact plan: one planned branch per requested artifact."""

    kind: ClassVar[str] = "creative.artifact_plan"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CreativeGenerateInput
    output_schema: ClassVar[type[BaseModel]] = ArtifactPlanOutput
    display_name: ClassVar[str] = "Artifact plan"
    description: ClassVar[str] = (
        "Plans the artifact family: one branch per requested artifact, each "
        "citing the shared decisions it will consume."
    )

    async def _execute(self, inputs: CreativeGenerateInput, ctx: NodeContext) -> ArtifactPlanOutput:
        context = inputs.shared_context
        requests = list(context.get("artifact_requests") or [])
        if not requests:
            raise ValueError("CreativeBrief carries no artifact requests to plan")
        message_id = inputs.message_decision_id or shared_decision_digest(context)
        visual_id = inputs.visual_decision_id or _digest(
            "visual",
            context.get("design_system_slug"),
            context.get("design_system_version"),
        )
        output = ArtifactPlanOutput(
            shared_context=context,
            artifact_plan_id=_digest("artifact_plan", [r.get("request_id") for r in requests]),
            message_decision_id=message_id,
            visual_decision_id=visual_id,
            artifact_requests=requests,
        )
        _record_shared_stage(ctx, stage="artifact.plan", decision_id=output.artifact_plan_id)
        return output


class CreativeArtifactGenerate(BaseNode[CreativeGenerateInput, ArtifactGenerateOutput]):
    """One artifact branch: generates against the shared decisions it consumed.

    The branch's static ``request`` parameter carries its own artifact request;
    the shared message/visual decisions arrive from the canonical predecessor
    outputs. The durable artifact record is written to the blackboard under
    ``artifact::<request_id>`` so fan-in stages see every branch, and echoed in
    the branch output so the recorded provenance cites exactly which shared
    decision identity produced this artifact.
    """

    kind: ClassVar[str] = "creative.artifact_generate"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CreativeGenerateInput
    output_schema: ClassVar[type[BaseModel]] = ArtifactGenerateOutput
    display_name: ClassVar[str] = "Artifact generate"
    description: ClassVar[str] = (
        "Generates one requested artifact against the shared decisions, and "
        "records which decision identities it consumed."
    )

    async def _execute(
        self, inputs: CreativeGenerateInput, ctx: NodeContext
    ) -> ArtifactGenerateOutput:
        context = inputs.shared_context or _shared_fallback(ctx)[0]
        decisions = _shared_fallback(ctx)[1]
        request = dict(inputs.request)
        request_id = request.get("request_id")
        if not request_id:
            raise ValueError("artifact branch carries no request_id")
        message_decision_id = inputs.message_decision_id or decisions.get(
            "message.architecture", ""
        )
        visual_decision_id = inputs.visual_decision_id or decisions.get("visual.direction", "")
        if not context:
            raise ValueError(f"branch {request_id!r} consumed no persisted shared context")
        if not message_decision_id:
            raise ValueError(f"branch {request_id!r} consumed no message decision")
        if not visual_decision_id:
            raise ValueError(f"branch {request_id!r} consumed no visual decision")

        content = self._compose(request, context)
        artifact_id = _digest(
            "artifact",
            request_id,
            message_decision_id,
            visual_decision_id,
            content,
        )
        output = ArtifactGenerateOutput(
            request_id=str(request_id),
            channel=str(request.get("channel") or ""),
            artifact_id=artifact_id,
            content=content,
            content_digest=_digest("content", content),
            consumed_message_decision_id=message_decision_id,
            consumed_visual_decision_id=visual_decision_id,
            goal_revision=int(context.get("goal_revision") or 0),
            brief_version=int(context.get("brief_version") or 0),
            shared_context=context,
        )
        if ctx.blackboard is not None:
            # Annotation values are strings by contract (dict[str, str]) and
            # merge per key across parallel siblings: one JSON record per
            # branch is the durable cross-branch artifact evidence.
            ctx.blackboard.node_annotations[artifact_annotation_key(str(request_id))] = (
                _canonical_json(
                    {
                        "artifact_id": artifact_id,
                        "request_id": str(request_id),
                        "channel": output.channel,
                        "content_digest": output.content_digest,
                        "consumed_message_decision_id": message_decision_id,
                        "consumed_visual_decision_id": visual_decision_id,
                        "goal_revision": output.goal_revision,
                        "brief_version": output.brief_version,
                    }
                )
            )
        return output

    def _compose(self, request: dict[str, Any], context: dict[str, Any]) -> str:
        """Deterministic draft composition. Products replace this stage's kind
        with their own provider-backed kind; the graph shape is unchanged."""
        messages = list(context.get("required_messages") or [])
        return (
            f"[{request.get('channel')}/{request.get('format')}"
            f"{' ' + request['dimensions'] if request.get('dimensions') else ''}] "
            f"for {context.get('audience')}: " + " | ".join(str(m) for m in messages)
        )


class CreativeCrossCritique(BaseNode[CritiqueInput, CrossCritiqueOutput]):
    """Cross-artifact critique: reads every branch's durable artifact record."""

    kind: ClassVar[str] = "creative.cross_critique"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CritiqueInput
    output_schema: ClassVar[type[BaseModel]] = CrossCritiqueOutput
    display_name: ClassVar[str] = "Cross-artifact critique"
    description: ClassVar[str] = (
        "Fan-in stage: verifies every planned branch produced a record and that "
        "all branches consumed the same shared decision identities."
    )

    async def _execute(self, inputs: CritiqueInput, ctx: NodeContext) -> CrossCritiqueOutput:
        annotations = _artifact_annotations(ctx)
        context = inputs.shared_context or _shared_fallback(ctx)[0]
        planned = {
            str(request.get("request_id")) for request in (context.get("artifact_requests") or [])
        }
        findings: list[str] = []
        for missing in sorted(planned - set(annotations)):
            findings.append(f"no artifact record for request {missing!r}")
        message_ids = {
            record.get("consumed_message_decision_id") for record in annotations.values()
        }
        visual_ids = {record.get("consumed_visual_decision_id") for record in annotations.values()}
        consistent = len(message_ids) <= 1 and len(visual_ids) <= 1
        if not consistent:
            findings.append("branches consumed different shared decisions")
        return CrossCritiqueOutput(
            shared_context=context,
            critique_id=_digest("critique", sorted(annotations)),
            artifact_count=len(annotations),
            shared_decision_consistent=consistent,
            findings=findings,
        )


class CreativeTargetedRefinement(BaseNode[CritiqueInput, TargetedRefinementOutput]):
    """Targeted refinement: only branches with findings are refined."""

    kind: ClassVar[str] = "creative.targeted_refinement"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CritiqueInput
    output_schema: ClassVar[type[BaseModel]] = TargetedRefinementOutput
    display_name: ClassVar[str] = "Targeted refinement"
    description: ClassVar[str] = (
        "Plans refinement per artifact record; branches without findings are "
        "named unchanged and are not reworked."
    )

    async def _execute(self, inputs: CritiqueInput, ctx: NodeContext) -> TargetedRefinementOutput:
        annotations = _artifact_annotations(ctx)
        context = inputs.shared_context or _shared_fallback(ctx)[0]
        planned = sorted(
            str(request.get("request_id")) for request in (context.get("artifact_requests") or [])
        )
        produced = sorted(annotations)
        return TargetedRefinementOutput(
            shared_context=context,
            refinement_id=_digest("refinement", produced),
            refined_request_ids=[rid for rid in planned if rid not in produced],
            unchanged_request_ids=[rid for rid in planned if rid in produced],
        )


class CreativeAcceptance(BaseNode[CritiqueInput, AcceptanceOutput]):
    """Acceptance: every planned branch produced an artifact against the shared decisions."""

    kind: ClassVar[str] = "creative.acceptance"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CritiqueInput
    output_schema: ClassVar[type[BaseModel]] = AcceptanceOutput
    display_name: ClassVar[str] = "Acceptance"
    description: ClassVar[str] = (
        "Accepts the artifact family only when every planned branch has a "
        "durable record citing the shared decisions."
    )

    async def _execute(self, inputs: CritiqueInput, ctx: NodeContext) -> AcceptanceOutput:
        annotations = _artifact_annotations(ctx)
        context = inputs.shared_context or _shared_fallback(ctx)[0]
        planned = sorted(
            str(request.get("request_id")) for request in (context.get("artifact_requests") or [])
        )
        accepted = [rid for rid in planned if rid in annotations]
        rejections = [
            f"request {rid!r} has no artifact record" for rid in planned if rid not in annotations
        ]
        return AcceptanceOutput(
            shared_context=context,
            acceptance_id=_digest("acceptance", accepted, rejections),
            accepted=not rejections,
            accepted_request_ids=accepted,
            rejections=rejections,
        )


class CreativePublishExport(BaseNode[CritiqueInput, PublishExportOutput]):
    """Publish/export: the accepted family, as recorded — nothing re-derived."""

    kind: ClassVar[str] = "creative.publish_export"
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = CritiqueInput
    output_schema: ClassVar[type[BaseModel]] = PublishExportOutput
    display_name: ClassVar[str] = "Publish / export"
    description: ClassVar[str] = (
        "Exports the accepted artifact family exactly as recorded, preserving "
        "the shared-decision citations in every record."
    )

    async def _execute(self, inputs: CritiqueInput, ctx: NodeContext) -> PublishExportOutput:
        annotations = _artifact_annotations(ctx)
        manifest = [annotations[request_id] for request_id in sorted(annotations)]
        return PublishExportOutput(
            export_id=_digest("export", manifest),
            manifest=manifest,
        )


def _artifact_annotations(ctx: NodeContext) -> dict[str, dict[str, Any]]:
    """Every branch's durable artifact record, parsed from the annotations."""
    if ctx.blackboard is None:
        return {}
    records: dict[str, dict[str, Any]] = {}
    for key, value in ctx.blackboard.node_annotations.items():
        if not str(key).startswith(ARTIFACT_ANNOTATION_PREFIX):
            continue
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, Mapping):
            records[str(key)[len(ARTIFACT_ANNOTATION_PREFIX) :]] = dict(parsed)
    return records


for _node_cls in (
    CreativeBriefResolve,
    CreativeResearchEvidence,
    CreativeMessageArchitecture,
    CreativeCopyPlatform,
    CreativeVisualDirection,
    CreativeArtifactPlan,
    CreativeArtifactGenerate,
    CreativeCrossCritique,
    CreativeTargetedRefinement,
    CreativeAcceptance,
    CreativePublishExport,
):
    register_node(_node_cls)
