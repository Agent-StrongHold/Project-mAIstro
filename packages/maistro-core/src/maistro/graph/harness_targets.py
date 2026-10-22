"""Harness components as evolvable targets (EPIC M4-E, issue #25).

M4-A's governed improvement substrate — optimizers, RSI cycles, tournaments —
already evolves genomes and Graph templates, but nothing *names* which harness
components a proposal is allowed to touch. `PipelineGenome.harness_params` is a
free-form dict and a `GraphTemplate` is an undifferentiated snapshot, so an
optimizer's output carries no statement of scope: nothing distinguishes "this
candidate changes the reviewer prompt" from "this candidate rewires the whole
topology and swaps authorized code", and nothing routes either through the
governed promotion gate.

This module is the epic-level substrate the two child work streams build on:

- a **closed vocabulary** (:class:`HarnessTargetKind`) of the harness component
  classes M4-A may evolve — prompts, tool selection/configuration, skills,
  memory/retrieval policy, planning strategy, subagent definitions, Graph
  topology, and authorized code;
- :class:`HarnessEvolutionProposal` — the artifact an optimizer produces: it
  names its base template, the component targets it touches, its rationale, and
  the canonical execution that produced it (a Run id is mandatory — a record
  names its producing execution, ADR-083026-e602; physical work stays on
  Graph -> Run -> NodeRun -> Attempt, never inside an optimizer or a foreign
  harness);
- :func:`materialize_candidate` / :func:`apply_harness_proposal` — the only
  sanctioned path from proposal to live template. Materialization always
  creates a **candidate** version (`GraphTemplate`'s field default is
  `"active"`, so an optimizer-constructed template could otherwise self-activate
  merely by being stored) and application routes through
  :func:`maistro.graph.templates.promote_audited`, consuming the governed
  promotion machinery (#21/#116) with its required
  :class:`~maistro.graph.templates.PromotionApproval` and audit entries rather
  than self-activating reusable changes.

Foreign harness sessions (harness_runner providers) stay provider metadata on
the canonical spine; nothing here gives an optimizer, a foreign harness, or
Turing its own execution identity.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro.graph.templates import (
    GraphTemplateNotFound,
    GraphTemplateStore,
    PromotionApproval,
    TemplatePromotionAudit,
    promote_audited,
)

__all__ = [
    "PROVENANCE_METADATA_KEY",
    "HarnessComponentTarget",
    "HarnessEvolutionProposal",
    "HarnessProposalInconsistent",
    "HarnessTargetBaseNotActive",
    "HarnessTargetKind",
    "HarnessTargetScopeMismatch",
    "apply_harness_proposal",
    "materialize_candidate",
]


class HarnessTargetKind(StrEnum):
    """The closed set of harness component classes M4-A may evolve.

    Deliberately closed: a proposal whose targets fall outside this enum cannot
    be constructed, so an optimizer cannot smuggle an unclassified component
    change (a new target kind is an epic-level decision, not a proposal field).
    """

    PROMPT = "prompt"
    TOOL_SELECTION = "tool_selection"
    SKILLS = "skills"
    MEMORY_RETRIEVAL_POLICY = "memory_retrieval_policy"
    PLANNING_STRATEGY = "planning_strategy"
    SUBAGENT_DEFINITIONS = "subagent_definitions"
    GRAPH_TOPOLOGY = "graph_topology"
    AUTHORIZED_CODE = "authorized_code"


PROVENANCE_METADATA_KEY = "harness_evolution"


class HarnessComponentTarget(BaseModel):
    """One harness component a proposal claims to improve.

    ``locator`` is the component's address inside the harness — a node id whose
    system prompt changes, a skill id, a binding id whose tool selection is
    reconfigured, and so on. It is a claim recorded for review and audit, not
    itself an authorization.
    """

    kind: HarnessTargetKind
    locator: str = Field(min_length=1)
    change_summary: str = Field(min_length=1)


class HarnessEvolutionProposal(BaseModel):
    """An M4-A optimizer's proposed improvement to one Graph template.

    Scope is fixed at construction: the proposal names exactly one
    ``template_id`` in exactly one ``workspace_id``, at least one target, and
    the Run that produced it. Application always creates a new candidate
    version — a proposal cannot target a version in place, and it carries no
    lifecycle of its own.
    """

    proposal_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    # None means "whatever version is currently active". Naming a version is
    # allowed for reproducibility, but only an *active* version may be the
    # base — a proposal that improves a candidate is a proposal to review, not
    # a lineage (see materialize_candidate).
    base_version: int | None = Field(default=None, ge=1)
    targets: list[HarnessComponentTarget] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    # ADR-083026-e602: a record names its producing execution. Optimizer work
    # is physical work on the canonical spine, so the producing Run is not
    # optional; the NodeRun is named when the proposal came from one node.
    produced_by_run_id: str = Field(min_length=1)
    produced_by_node_id: str | None = None
    candidate_nodes: list[Node] = Field(default_factory=list)
    candidate_edges: list[Edge] = Field(default_factory=list)
    candidate_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _identifier_fields_are_not_blank(self) -> HarnessEvolutionProposal:
        """Same posture as `PromotionApproval`: min_length counts whitespace,
        so an identifier of spaces would otherwise pass."""
        blank = [
            field
            for field in (
                "proposal_id",
                "workspace_id",
                "template_id",
                "rationale",
                "produced_by_run_id",
                *(["produced_by_node_id"] if self.produced_by_node_id is not None else []),
            )
            if not getattr(self, field).strip()
        ]
        if blank:
            raise ValueError(f"identifier fields must not be blank: {', '.join(blank)}")
        for index, target in enumerate(self.targets):
            if not target.locator.strip() or not target.change_summary.strip():
                raise ValueError(f"targets[{index}]: locator and change_summary must not be blank")
        return self

    @model_validator(mode="after")
    def _candidate_edges_reference_candidate_nodes(self) -> HarnessEvolutionProposal:
        """Fail at proposal time, not at materialization time.

        The same rule `GraphTemplate` enforces on itself; restating it here
        means a malformed proposal is refused when the optimizer emits it,
        before it is persisted anywhere.
        """
        node_ids = {node.node_id for node in self.candidate_nodes}
        for edge in self.candidate_edges:
            if edge.from_node not in node_ids or edge.to_node not in node_ids:
                raise ValueError(
                    f"candidate edge {edge.edge_id} references a node outside "
                    "the candidate topology"
                )
        return self


class HarnessTargetScopeMismatch(ValueError):
    """The proposal's workspace does not own the base template."""


class HarnessTargetBaseNotActive(ValueError):
    """The named base version exists but is not active."""


class HarnessProposalInconsistent(ValueError):
    """The proposal's declared targets contradict its candidate content."""


async def _resolve_base(
    store: GraphTemplateStore, proposal: HarnessEvolutionProposal
) -> GraphTemplate:
    """Fetch the proposal's base version, refusing anything but an active one.

    A named base version must exist and be active; the unnamed form resolves
    whatever version the store currently serves as active. Both refusals name
    the registered versions so an optimizer operator can see what *is* there.
    """
    if proposal.base_version is not None:
        base = await store.get(proposal.template_id, version=proposal.base_version)
        if base is None:
            known = await store.versions(proposal.template_id)
            if not known:
                raise GraphTemplateNotFound(
                    f"no GraphTemplate {proposal.template_id!r} is registered"
                )
            raise GraphTemplateNotFound(
                f"GraphTemplate {proposal.template_id!r} has no version "
                f"{proposal.base_version}; registered versions: "
                f"{', '.join(str(item) for item in known)}"
            )
        if base.lifecycle != "active":
            raise HarnessTargetBaseNotActive(
                f"GraphTemplate {proposal.template_id!r} version "
                f"{proposal.base_version} is {base.lifecycle}, not active; a "
                "proposal improves the active version"
            )
        return base
    base = await store.get(proposal.template_id)
    if base is None:
        known = await store.versions(proposal.template_id)
        if not known:
            raise GraphTemplateNotFound(f"no GraphTemplate {proposal.template_id!r} is registered")
        raise GraphTemplateNotFound(
            f"GraphTemplate {proposal.template_id!r} has no active version "
            f"to improve; registered versions: "
            f"{', '.join(str(item) for item in known)}"
        )
    return base


async def materialize_candidate(
    store: GraphTemplateStore, proposal: HarnessEvolutionProposal
) -> GraphTemplate:
    """Register the proposal's content as the template's next candidate version.

    The active base is never mutated: a new version number is allocated, the
    candidate is stored with ``lifecycle="candidate"`` (overriding
    `GraphTemplate`'s `"active"` field default — this is the self-activation
    the epic forbids), and the evolution provenance is stamped into the
    version's metadata so every future inspection of the version can see which
    proposal, run, and targets produced it.

    Raises:
        GraphTemplateNotFound: no such template, or no active version to
            improve (from :func:`_resolve_base`).
        HarnessTargetScopeMismatch: the template belongs to another workspace.
        HarnessTargetBaseNotActive: the explicitly named base version is not
            active (from :func:`_resolve_base`).
        HarnessProposalInconsistent: the proposal declares a ``graph_topology``
            target but its candidate topology is identical to the base's — a
            no-op diff may not claim to have rewired the graph.
        GraphTemplateConflict: surfaced from the store; unreachable in normal
            flow because a fresh version number is always allocated.
    """
    base = await _resolve_base(store, proposal)

    if base.workspace_id != proposal.workspace_id:
        raise HarnessTargetScopeMismatch(
            f"proposal workspace {proposal.workspace_id!r} does not own "
            f"GraphTemplate {proposal.template_id!r} (workspace {base.workspace_id!r})"
        )

    kinds = {target.kind for target in proposal.targets}
    if HarnessTargetKind.GRAPH_TOPOLOGY in kinds and _topology(
        proposal.candidate_nodes, proposal.candidate_edges
    ) == _topology(base.nodes, base.edges):
        raise HarnessProposalInconsistent(
            "proposal declares a graph_topology target but its candidate "
            "topology is identical to the base version's"
        )

    known_versions = await store.versions(proposal.template_id)
    next_version = max(known_versions) + 1 if known_versions else 1

    candidate = GraphTemplate(
        template_id=proposal.template_id,
        workspace_id=proposal.workspace_id,
        version=next_version,
        # The field default is "active"; an optimizer artifact must never
        # activate by being stored. `promote_audited` is what changes this.
        lifecycle="candidate",
        name=base.name,
        description=base.description,
        nodes=proposal.candidate_nodes,
        edges=proposal.candidate_edges,
        metadata={
            **base.metadata,
            **proposal.candidate_metadata,
            PROVENANCE_METADATA_KEY: {
                "proposal_id": proposal.proposal_id,
                "targets": sorted(target.kind.value for target in proposal.targets),
                "target_locators": sorted(target.locator for target in proposal.targets),
                "rationale": proposal.rationale,
                "produced_by_run_id": proposal.produced_by_run_id,
                "produced_by_node_id": proposal.produced_by_node_id,
                "base_version": base.version,
            },
        },
    )
    await store.put(candidate)
    return candidate


async def apply_harness_proposal(
    store: GraphTemplateStore,
    proposal: HarnessEvolutionProposal,
    *,
    audit: TemplatePromotionAudit,
    approval: PromotionApproval,
) -> GraphTemplate:
    """Materialize the proposal and promote it through the governed gate.

    This is the only sanctioned path from proposal to live template, exactly as
    `PopulationStore.promote_audited` is the only sanctioned path for a genome:
    the candidate version is created, then
    :func:`maistro.graph.templates.promote_audited` runs its
    attempt -> promoting -> committed -> active sequence under the required
    approval and audit sink. There is deliberately no argument that skips the
    gate — a harness improvement that can bypass promotion is not governed
    improvement.
    """
    candidate = await materialize_candidate(store, proposal)
    await promote_audited(
        store,
        candidate.template_id,
        candidate.version,
        audit=audit,
        approval=approval,
    )
    promoted = await store.get(candidate.template_id, version=candidate.version)
    if promoted is None:  # pragma: no cover - the store just stored it
        raise GraphTemplateNotFound(
            f"GraphTemplate {candidate.template_id!r} version "
            f"{candidate.version} vanished during promotion"
        )
    return promoted


def _topology(nodes: list[Node], edges: list[Edge]) -> Any:
    """The structural snapshot a ``graph_topology`` target claims to change.

    Node identity and type plus edge identity, direction, and condition — not
    node content. A prompt-only candidate therefore cannot satisfy (or be
    falsely accused of) a topology claim.
    """
    return (
        [(node.node_id, node.node_type) for node in nodes],
        [(edge.edge_id, edge.from_node, edge.to_node, edge.condition) for edge in edges],
    )
