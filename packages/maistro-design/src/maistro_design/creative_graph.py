"""The creative Graph: plan, provenance binding, invalidation, inspection (#775).

One canonical Project Goal is fulfilled by one coordinated artifact family
through one selected canonical Graph and its canonical Run — not by
independent generator calls. This module is the Design-Studio-side planner
around the **canonical** Graph/Run machinery (`maistro.graph`):

- :func:`plan_creative_graph` builds a canonical
  :class:`maistro.graph.definitions.GraphTemplate` for one CreativeBrief
  version: shared upstream decisions (research/evidence, message
  architecture, copy platform, visual direction, artifact plan) become
  single durable stages, then one branch per requested artifact fans out in
  parallel, then cross-artifact critique, targeted refinement, acceptance
  and publish/export fan back in.
- :func:`instantiate_creative_graph` instantiates the template through the
  canonical ``GraphTemplate.instantiate`` and binds the exact Goal
  identity/revision and accountable/delegated Agent provenance into the
  instantiated Graph's metadata.
- :func:`run_creative_graph` launches the graph through the canonical
  ``run_durable_graph`` executor, recording the same provenance on the
  canonical Run. Execution, retries, Attempts and recovery stay entirely in
  the canonical machinery.
- :func:`invalidated_requests` is a *pure* dependency answer: given two
  CreativeBrief versions (or a Goal revision change), which planned branches
  and shared stages are semantically affected. It is planning/inspection
  arithmetic, not a runtime dependency engine — the caller re-plans and
  re-runs through canonical state.
- :func:`artifact_provenance` inspects a persisted canonical
  ``DurableRunRecord`` and explains, per artifact, which Goal revision,
  CreativeBrief version, shared decision identities and Agent delegation
  produced it.

Nothing here owns Goals, Runs, NodeRuns or Attempts; nothing here schedules,
retries or tracks dependencies at runtime. The stop condition from #773/#775
holds: this is product-local planning and inspection over canonical
execution semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import Edge, Graph, GraphTemplate, Node
from maistro.graph.durable_runs import run_durable_graph
from maistro.graph.durable_runs.types import DurableRunRecord

from .brief import CreativeBrief
from .creative_nodes import (
    ARTIFACT_ANNOTATION_PREFIX,
    shared_context_from_brief,
)

if TYPE_CHECKING:
    from maistro.graph.durable_runs.protocol import DurableRunStore

__all__ = [
    "ARTIFACT_GENERATE_NODE_PREFIX",
    "CREATIVE_GRAPH_TEMPLATE_NAME",
    "SHARED_STAGE_NODE_IDS",
    "ArtifactProvenanceRecord",
    "CreativeGraphPlan",
    "InvalidationReport",
    "artifact_annotation_to_provenance",
    "artifact_provenance",
    "branch_node_id",
    "channel_family",
    "creative_run_provenance",
    "instantiate_creative_graph",
    "invalidated_requests",
    "plan_creative_graph",
    "run_creative_graph",
]


CREATIVE_GRAPH_TEMPLATE_NAME = "creative-production"
"""The reference creative-production GraphTemplate name (#775)."""

ARTIFACT_GENERATE_NODE_PREFIX = "artifact.generate."
"""Template node-id prefix of one artifact branch."""

#: Shared upstream decisions, in reference-graph order. One durable stage
#: each; every artifact branch consumes their outputs.
SHARED_STAGE_NODE_IDS: tuple[str, ...] = (
    "brief.resolve",
    "research.evidence",
    "message.architecture",
    "copy.platform",
    "visual.direction",
    "artifact.plan",
)

_DOWNSTREAM_SHARED_NODE_IDS: tuple[str, ...] = (
    "cross.critique",
    "targeted.refinement",
    "acceptance",
    "publish.export",
)

_CHANNEL_FAMILIES: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"website", "landing_page", "landing page", "web", "webpage", "site", "code"}),
        "website_code",
    ),
    (frozenset({"deck", "slides", "slide", "presentation", "pitch"}), "deck"),
    (
        frozenset(
            {
                "poster",
                "flyer",
                "banner",
                "social",
                "social_post",
                "visual",
                "image",
                "fixed_page",
                "print",
            }
        ),
        "fixed_page_visual",
    ),
    (frozenset({"script", "video", "audio", "media", "film", "podcast"}), "script_video_media"),
)


def channel_family(channel: str) -> str:
    """The specialized subgraph family a channel plans into.

    The exact node decomposition may vary by requested artifacts (#775); the
    family records which specialization a branch belongs to so products can
    swap provider-backed kinds per family without changing the graph shape.
    """
    normalized = channel.strip().lower().replace("-", "_").replace(" ", "_")
    for channels, family in _CHANNEL_FAMILIES:
        if normalized in channels:
            return family
    return "generic"


def branch_node_id(request_id: str) -> str:
    return f"{ARTIFACT_GENERATE_NODE_PREFIX}{request_id}"


@dataclass(frozen=True)
class CreativeGraphPlan:
    """The planned template plus the branch structure derived from one brief."""

    template: GraphTemplate
    brief_id: str
    brief_version: int
    goal_id: str
    goal_revision: int
    branch_request_ids: tuple[str, ...]
    branch_node_ids: tuple[str, ...]
    shared_stage_node_ids: tuple[str, ...] = SHARED_STAGE_NODE_IDS

    @property
    def template_ref(self) -> dict[str, Any]:
        """Selection reference for ``CreativeBrief.fulfillment_graph_ref``-shaped slots."""
        return {
            "template_id": self.template.template_id,
            "version": self.template.version,
            "content_hash": self.template.content_hash,
            "name": self.template.name,
        }


def plan_creative_graph(
    brief: CreativeBrief,
    *,
    template_id: str | None = None,
    version: int | None = None,
) -> CreativeGraphPlan:
    """Plan the reference creative-production GraphTemplate for one brief version.

    Shared upstream decisions are single stages; every requested artifact gets
    its own branch node fanning out from ``artifact.plan`` in parallel and
    fanning into ``cross.critique``. The template records the brief/goal/agent
    references as selection metadata (references, never a second identity
    store).

    ``version`` defaults to the brief's own version: each CreativeBrief version
    in a lineage plans distinct content under the lineage's template id, so it
    registers as the matching next template version instead of colliding with
    the already-registered v1 definition. Pass ``version`` explicitly only to
    re-plan the same brief version (e.g. after a rejected registration).
    """
    requests = list(brief.artifact_requests)
    if not requests:
        raise ValueError("CreativeBrief carries no artifact requests; nothing to plan")

    nodes: list[Node] = []
    edges: list[Edge] = []

    def add_stage(node_id: str, kind: str, *, stage: str, **node_kwargs: Any) -> Node:
        node = Node(
            node_id=node_id,
            node_type=kind,
            name=stage,
            metadata={"stage": stage, "branch": "shared"},
            **node_kwargs,
        )
        nodes.append(node)
        return node

    add_stage("brief.resolve", "creative.brief_resolve", stage="brief.resolve")
    add_stage("research.evidence", "creative.research_evidence", stage="research.evidence")
    add_stage("message.architecture", "creative.message_architecture", stage="message.architecture")
    add_stage("copy.platform", "creative.copy_platform", stage="copy.platform")
    add_stage("visual.direction", "creative.visual_direction", stage="visual.direction")
    add_stage("artifact.plan", "creative.artifact_plan", stage="artifact.plan")
    for upstream, downstream in pairwise(SHARED_STAGE_NODE_IDS):
        edges.append(Edge(from_node=upstream, to_node=downstream))

    branch_ids: list[str] = []
    for request in requests:
        node_id = branch_node_id(request.request_id)
        branch_ids.append(node_id)
        nodes.append(
            Node(
                node_id=node_id,
                node_type="creative.artifact_generate",
                name=f"generate {request.request_id}",
                # The branch's own request is a static graph input/constraint —
                # a locked decision, not silent mutable state.
                parameters={"request": request.model_dump(mode="json")},
                policies={"max_attempts": 3},
                metadata={
                    "stage": "artifact.generate",
                    "branch": request.request_id,
                    "channel": request.channel,
                    "channel_family": channel_family(request.channel),
                },
            )
        )
        # Fan out from the plan; fan in to the critique.
        edges.append(Edge(from_node="artifact.plan", to_node=node_id, metadata={"parallel": True}))
        edges.append(Edge(from_node=node_id, to_node="cross.critique"))

    add_stage("cross.critique", "creative.cross_critique", stage="cross.critique")
    add_stage("targeted.refinement", "creative.targeted_refinement", stage="targeted.refinement")
    add_stage("acceptance", "creative.acceptance", stage="acceptance")
    add_stage("publish.export", "creative.publish_export", stage="publish.export")
    for upstream, downstream in pairwise(_DOWNSTREAM_SHARED_NODE_IDS):
        edges.append(Edge(from_node=upstream, to_node=downstream))

    template = GraphTemplate(
        template_id=template_id or f"creative-production-{brief.lineage_id}",
        workspace_id=brief.workspace_id,
        # Distinct brief versions plan distinct content under one lineage
        # template id (Codex review): defaulting the template version to the
        # brief version keeps re-registering an updated brief out of
        # ``GraphTemplateConflict``.
        version=version if version is not None else brief.version,
        name=CREATIVE_GRAPH_TEMPLATE_NAME,
        description=(
            "Reference creative-production graph: shared decisions once, "
            "parallel artifact branches, cross-artifact critique, targeted "
            "refinement, acceptance, publish/export (#775)."
        ),
        nodes=nodes,
        edges=edges,
        metadata={
            "entry_node": "brief.resolve",
            "creative": {
                "goal_id": brief.goal_id,
                "goal_revision": brief.goal_revision,
                "brief_id": brief.brief_id,
                "brief_lineage_id": brief.lineage_id,
                "brief_version": brief.version,
                "goal_owner_agent_id": brief.goal_owner_agent_id,
                "persona_id": brief.persona_id,
                "design_system_slug": brief.design_system_slug,
                "branch_request_ids": [request.request_id for request in requests],
            },
        },
    )
    return CreativeGraphPlan(
        template=template,
        brief_id=brief.brief_id,
        brief_version=brief.version,
        goal_id=brief.goal_id,
        goal_revision=brief.goal_revision,
        branch_request_ids=tuple(request.request_id for request in requests),
        branch_node_ids=tuple(branch_ids),
    )


def creative_run_provenance(
    brief: CreativeBrief, *, plan: CreativeGraphPlan | None = None
) -> dict[str, Any]:
    """The canonical Run provenance binding for one creative fulfillment.

    Recorded on the canonical Run so the selected Graph/Run retains the exact
    Goal revision and accountable/delegated Agent provenance (#775).
    """
    provenance: dict[str, Any] = {
        "relationship": "goal_run_evidence",
        "goal_id": brief.goal_id,
        "goal_revision": brief.goal_revision,
        "brief_id": brief.brief_id,
        "brief_lineage_id": brief.lineage_id,
        "brief_version": brief.version,
        "goal_owner_agent_id": brief.goal_owner_agent_id,
        "goal_delegation_ref": (
            brief.goal_delegation_ref.model_dump(mode="json")
            if brief.goal_delegation_ref is not None
            else None
        ),
        "persona_id": brief.persona_id,
        "design_system_slug": brief.design_system_slug,
    }
    if plan is not None:
        provenance["graph_template"] = plan.template_ref
    return provenance


def instantiate_creative_graph(
    brief: CreativeBrief,
    *,
    plan: CreativeGraphPlan | None = None,
    project_id: str | None = None,
    graph_id: str | None = None,
) -> Graph:
    """Instantiate the planned template into a canonical Project Graph.

    ``project_id`` defaults to the brief's own Project; the instantiated
    Graph's metadata carries the creative provenance block (exact Goal
    revision, brief version, agent ownership/delegation) verbatim.
    """
    template = plan.template if plan is not None else plan_creative_graph(brief).template
    graph = template.instantiate(
        project_id=project_id or brief.project_id,
        graph_id=graph_id,
    )
    graph.metadata["creative_provenance"] = creative_run_provenance(brief, plan=plan)
    return graph


async def run_creative_graph(
    brief: CreativeBrief,
    *,
    store: DurableRunStore,
    graph: Graph | None = None,
    plan: CreativeGraphPlan | None = None,
    node_resolver: Any = None,
    run_store: Any | None = None,
    run_id: str | None = None,
    actor_principal_id: str | None = None,
    max_steps: int = 256,
) -> DurableRunRecord:
    """Plan, instantiate and launch one creative fulfillment Run — canonically.

    All physical work goes through the canonical durable executor: canonical
    Run/NodeRun/Attempt seams, canonical provenance, canonical recovery. The
    CreativeBrief travels as the launch input; the shared context stages
    resolve it exactly once.
    """
    from maistro.graph.nodes import get_node  # local import: registry is global

    from . import creative_nodes  # noqa: F401  # ensure kinds registered

    if graph is None:
        if plan is None:
            # Retain the auto-selected plan so both the Graph metadata and the
            # Run provenance below report the instantiated template (#775).
            plan = plan_creative_graph(brief)
        graph = instantiate_creative_graph(brief, plan=plan)
    resolver = node_resolver

    def default_resolver(node_id: str, resolved_graph: Graph) -> Any:
        spec = next(node for node in resolved_graph.nodes if node.node_id == node_id)
        return get_node(spec.node_type)()

    return await run_durable_graph(
        graph,
        store=store,
        node_resolver=resolver or default_resolver,
        inputs={
            "brief": {
                "workspace_id": brief.workspace_id,
                "project_id": brief.project_id,
                "goal_id": brief.goal_id,
                "goal_revision": brief.goal_revision,
                "brief_id": brief.brief_id,
                "brief_version": brief.version,
                "shared_context": shared_context_from_brief(brief),
            }
        },
        provenance=creative_run_provenance(brief, plan=plan),
        actor_principal_id=actor_principal_id or brief.goal_owner_agent_id,
        run_id=run_id,
        run_store=run_store,
        max_steps=max_steps,
    )


# ---------------------------------------------------------------------------
# Invalidation arithmetic (pure, no runtime engine)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvalidationReport:
    """Which planned work a CreativeBrief/Goal change semantically affects.

    Pure arithmetic over two brief versions and the planned branch structure.
    A changed shared decision invalidates every descendant that consumes it;
    a changed Goal revision invalidates everything that semantically depends
    on Goal state; a branch-local change (e.g. one poster dimension)
    invalidates only that branch. Historical Runs/artifacts are never touched
    — the caller plans new work from the new version.
    """

    goal_revision_changed: bool
    shared_context_changed: bool
    invalidated_request_ids: tuple[str, ...]
    unchanged_request_ids: tuple[str, ...]
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def invalidated_node_ids(self) -> tuple[str, ...]:
        """Planned template node ids the change invalidates, ancestors first.

        The shared decision stages rerun only when the shared context actually
        changed: a branch-local change (e.g. one poster dimension) must not
        re-decide ``brief.resolve``…``artifact.plan``, whose outputs branches
        left unchanged still consume. The post-branch shared stages always
        rerun — they fan-in over every branch's outputs.
        """
        if not self.invalidated_request_ids:
            return ()
        shared_stage_ids = SHARED_STAGE_NODE_IDS if self.shared_context_changed else ()
        return (
            shared_stage_ids
            + tuple(branch_node_id(request_id) for request_id in self.invalidated_request_ids)
            + _DOWNSTREAM_SHARED_NODE_IDS
        )


def _shared_signature(brief: CreativeBrief) -> dict[str, Any]:
    """The shared-decision fields whose change invalidates all descendants.

    Mirrors the slice :func:`maistro_design.creative_nodes.shared_decision_digest`
    digests — the shared decisions every branch consumes through the relayed
    shared context, including who owns/delegates the Goal and who benefits,
    the success interpretation, the source references the work builds on and
    any supervision constraints.
    The invalidation answer and the decision identities the message/visual
    stages cite must never disagree about what counts as a shared decision:
    a field whose change moves the digest without invalidating descendants
    would re-plan branches onto stale decisions (#775 repair).
    """
    return {
        "goal_revision": brief.goal_revision,
        "goal_owner_agent_id": brief.goal_owner_agent_id,
        "goal_delegation_ref": (
            brief.goal_delegation_ref.model_dump(mode="json")
            if brief.goal_delegation_ref is not None
            else None
        ),
        "persona": (brief.persona.ref_id, brief.persona.version),
        "design_system": (brief.design_system.ref_id, brief.design_system.version),
        "audience": brief.audience,
        "beneficiaries": list(brief.beneficiaries),
        "success_interpretation": brief.success_interpretation,
        "required_messages": list(brief.required_messages),
        "cta": brief.cta,
        "required_facts": [fact.model_dump(mode="json") for fact in brief.required_facts],
        "prohibited_claims": list(brief.prohibited_claims),
        "tone_constraints": list(brief.tone_constraints),
        "source_references": [
            reference.model_dump(mode="json") for reference in brief.source_references
        ],
        "supervision_constraints": list(brief.supervision_constraints),
    }


def invalidated_requests(old: CreativeBrief, new: CreativeBrief) -> InvalidationReport:
    """Which branches/shared stages a brief (or Goal revision) change affects."""
    if old.lineage_id != new.lineage_id:
        raise ValueError("invalidation compares versions of one brief lineage")

    reasons: dict[str, str] = {}
    goal_changed = old.goal_revision != new.goal_revision
    old_shared = _shared_signature(old)
    new_shared = _shared_signature(new)
    shared_changed = goal_changed or any(
        old_shared[field] != new_shared[field] for field in old_shared
    )
    if goal_changed:
        reasons["*"] = (
            f"canonical Goal revision changed {old.goal_revision} -> {new.goal_revision}; "
            "work that semantically depends on Goal state is invalidated"
        )
    elif shared_changed:
        changed_fields = sorted(
            field for field in old_shared if old_shared[field] != new_shared[field]
        )
        reasons["*"] = (
            f"shared decision changed ({', '.join(changed_fields)}); every descendant "
            "consuming the shared decisions is invalidated"
        )

    old_requests = {request.request_id: request for request in old.artifact_requests}
    new_requests = {request.request_id: request for request in new.artifact_requests}
    invalidated: list[str] = []
    unchanged: list[str] = []
    for request_id in sorted(set(old_requests) | set(new_requests)):
        old_request = old_requests.get(request_id)
        new_request = new_requests.get(request_id)
        if old_request is None:
            invalidated.append(request_id)
            reasons[request_id] = "artifact request added"
            continue
        if new_request is None:
            invalidated.append(request_id)
            reasons[request_id] = "artifact request removed"
            continue
        if shared_changed:
            invalidated.append(request_id)
            continue
        changed = [
            field_name
            for field_name in ("channel", "format", "dimensions", "requirements")
            if getattr(old_request, field_name) != getattr(new_request, field_name)
        ]
        if changed:
            invalidated.append(request_id)
            reasons[request_id] = f"artifact request changed: {', '.join(sorted(changed))}"
        else:
            unchanged.append(request_id)

    return InvalidationReport(
        goal_revision_changed=goal_changed,
        shared_context_changed=shared_changed,
        invalidated_request_ids=tuple(invalidated),
        unchanged_request_ids=tuple(unchanged),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Inspection: explain each artifact's lineage from canonical state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactProvenanceRecord:
    """One artifact's explained lineage, read from canonical Run state."""

    request_id: str
    node_id: str
    channel: str
    artifact_id: str
    content_digest: str
    goal_id: str
    goal_revision: int
    brief_id: str
    brief_version: int
    goal_owner_agent_id: str
    goal_delegation_ref: dict[str, Any] | None
    consumed_message_decision_id: str
    consumed_visual_decision_id: str
    status: str
    attempt_count: int
    node_run_ids: tuple[str, ...]


def artifact_provenance(record: DurableRunRecord) -> tuple[ArtifactProvenanceRecord, ...]:
    """Explain which Goal revision, brief version, shared decisions and agent
    delegation produced each artifact — from the persisted canonical record.

    Reconstruction reads only canonical state (Run provenance, NodeRuns,
    Attempts, the graph snapshot and the blackboard snapshot); it replays no
    workflow and consults no client memory.
    """
    provenance = dict(record.run.provenance)
    graph_snapshot = record.run.graph.materialize()
    # Instantiation mints fresh node identities; branch identity survives in
    # the node's definition metadata ("stage"/"branch"), not in the node id.
    branch_node_by_request = {
        str(node.metadata.get("branch")): node
        for node in graph_snapshot.nodes
        if node.metadata.get("stage") == "artifact.generate"
    }
    annotations: dict[str, dict[str, Any]] = {}
    for key, value in (
        record.graph_state.blackboard_snapshot.get("node_annotations") or {}
    ).items():
        if not str(key).startswith(ARTIFACT_ANNOTATION_PREFIX):
            continue
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            annotations[str(key)[len(ARTIFACT_ANNOTATION_PREFIX) :]] = parsed

    node_runs_by_node: dict[str, list[Any]] = {}
    attempts_by_node_run: dict[str, list[Any]] = {}
    for node_run in record.node_runs:
        node_runs_by_node.setdefault(node_run.node_id, []).append(node_run)
    for attempt in record.attempts:
        attempts_by_node_run.setdefault(attempt.node_run_id, []).append(attempt)

    records: list[ArtifactProvenanceRecord] = []
    for request_id in sorted(set(annotations) | set(branch_node_by_request)):
        annotation = annotations.get(request_id, {})
        node = branch_node_by_request.get(request_id)
        runs = list(node_runs_by_node.get(node.node_id, [])) if node is not None else []
        if not runs:
            # A planned branch that never executed (e.g. the run failed before
            # it): provenance stays explainable as planned-only.
            status = "planned"
            attempt_count = 0
            run_ids: tuple[str, ...] = ()
        else:
            status = str(runs[-1].status.value)
            attempt_count = sum(
                len(attempts_by_node_run.get(node_run.node_run_id, [])) for node_run in runs
            )
            run_ids = tuple(node_run.node_run_id for node_run in runs)
        records.append(
            ArtifactProvenanceRecord(
                request_id=request_id,
                node_id=node.node_id if node is not None else branch_node_id(request_id),
                channel=str(
                    annotation.get("channel") or (node.metadata.get("channel") if node else "")
                ),
                artifact_id=str(annotation.get("artifact_id") or ""),
                content_digest=str(annotation.get("content_digest") or ""),
                goal_id=str(provenance.get("goal_id") or ""),
                goal_revision=int(
                    annotation.get("goal_revision") or provenance.get("goal_revision") or 0
                ),
                brief_id=str(provenance.get("brief_id") or ""),
                brief_version=int(
                    annotation.get("brief_version") or provenance.get("brief_version") or 0
                ),
                goal_owner_agent_id=str(provenance.get("goal_owner_agent_id") or ""),
                goal_delegation_ref=provenance.get("goal_delegation_ref"),
                consumed_message_decision_id=str(
                    annotation.get("consumed_message_decision_id") or ""
                ),
                consumed_visual_decision_id=str(
                    annotation.get("consumed_visual_decision_id") or ""
                ),
                status=status,
                attempt_count=attempt_count,
                node_run_ids=run_ids,
            )
        )
    return tuple(records)


def artifact_annotation_to_provenance(annotation: dict[str, Any]) -> dict[str, Any]:
    """The lineage keys one branch record carries (inspection helper)."""
    return {
        key: annotation[key]
        for key in (
            "goal_revision",
            "brief_version",
            "consumed_message_decision_id",
            "consumed_visual_decision_id",
        )
        if key in annotation
    }


if TYPE_CHECKING:
    #: Vulture references: the public planning/invalidation surface is
    #: re-exported from ``maistro_design`` and exercised by the tests, and
    #: ``ArtifactProvenanceRecord`` is serialized with ``asdict()`` by the
    #: Conductor inspection path (#775: which Goal revision, CreativeBrief
    #: version, shared decision and Agent delegation produced each artifact),
    #: so no direct read exists in this scan set. The tuple is scanner input
    #: only (never evaluated at runtime): class-level access to required
    #: dataclass fields raises AttributeError, so the references must stay
    #: type-check-time.
    _VULTURE_REFERENCES = (
        CreativeGraphPlan.branch_request_ids,
        CreativeGraphPlan.branch_node_ids,
        CreativeGraphPlan.shared_stage_node_ids,
        InvalidationReport.goal_revision_changed,
        InvalidationReport.unchanged_request_ids,
        InvalidationReport.invalidated_node_ids,
        ArtifactProvenanceRecord.consumed_message_decision_id,
        ArtifactProvenanceRecord.consumed_visual_decision_id,
    )
