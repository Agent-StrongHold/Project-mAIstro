"""Hydration: projecting durable memory into a Workspace's working graph.

Hydration is a deterministic read of authoritative records (ADR-082226-5104:
PostgreSQL + pgvector is the durable system of record; the working graph is
hydrated from it and is never authoritative). No model-backed extraction
happens here — any model-backed disambiguation or entity resolution is #301/M4
work and must go through the governed Capability/Invocation path; the M3 floor
projects records as they durably are.

The seam is source-protocol based so consuming products (#773/#777) and server
wiring can adapt the stores a deployment actually has, without this module
growing a second memory store: every source here *reads* existing durable
stores, it never writes any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from maistro.memory.working_graph.types import (
    CanonicalRef,
    EdgeRelation,
    NodeKind,
    WorkingGraphEdge,
    WorkingGraphNode,
    node_id_for,
)
from maistro.protocols.memory import EpisodicStore, LearningStore
from maistro.types.memory import EpisodicMemory, Learning, MemoryScope

#: Upper bound one source may contribute; hydration must stay a bounded,
#: lazy operation (ADR-082226-5104: graphs are lazy, evictable, per active
#: Workspace — not a bulk import of the database).
DEFAULT_HYDRATION_LIMIT = 200


@dataclass
class ScopeSelection:
    """The durable scope axes one Workspace maps onto.

    Each axis is opt-in: ``None`` means "this Workspace puts no constraint on
    that axis", a value means only records carrying exactly that value hydrate.
    Deployments own the mapping (Workspace → org/user/project …); this module
    refuses to invent one.
    """

    org_id: str | None = None
    team_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    project_id: str | None = None


@dataclass
class ArtifactVersionRecord:
    """One artifact version as durably recorded (e.g. accepted / rejected)."""

    artifact_id: str
    version: str
    status: str
    workspace_id: str
    summary: str = ""
    kind: str = ""
    run_id: str = ""
    node_run_id: str = ""
    project_id: str = ""
    goal_id: str = ""
    persona_id: str = ""
    user_id: str = ""


@dataclass
class RunProvenanceRecord:
    """The canonical execution provenance one Run contributes (#64)."""

    run_id: str
    workspace_id: str
    status: str = ""
    goal_id: str = ""
    graph_id: str = ""
    project_id: str = ""
    persona_id: str = ""
    parent_run_id: str = ""
    summary: str = ""


@dataclass
class TerminologyRecord:
    """One Workspace terminology entry (term → definition)."""

    term: str
    workspace_id: str
    definition: str = ""
    project_id: str = ""


@runtime_checkable
class ArtifactSource(Protocol):
    """Durable artifact versions for one Workspace (accepted, rejected, …)."""

    async def versions_for_workspace(
        self, workspace_id: str, *, limit: int
    ) -> list[ArtifactVersionRecord]: ...


@runtime_checkable
class RunProvenanceSource(Protocol):
    """Recent canonical Runs for one Workspace (Goal → Graph → Run spine)."""

    async def recent_runs(self, workspace_id: str, *, limit: int) -> list[RunProvenanceRecord]: ...


@runtime_checkable
class TerminologySource(Protocol):
    """Workspace terminology entries."""

    async def terms_for_workspace(
        self, workspace_id: str, *, limit: int
    ) -> list[TerminologyRecord]: ...


@dataclass
class WorkingMemorySnapshot:
    """The nodes and edges one hydration pass materialised for a Workspace."""

    workspace_id: str
    nodes: list[WorkingGraphNode] = field(default_factory=list)
    edges: list[WorkingGraphEdge] = field(default_factory=list)


@runtime_checkable
class WorkingMemorySource(Protocol):
    """One durable store's projection into a Workspace's working graph."""

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot: ...


def _learning_in_scope(learning: Learning, scope: ScopeSelection) -> bool:
    for axis_value, learning_value in (
        (scope.org_id, learning.org_id),
        (scope.team_id, learning.team_id),
        (scope.user_id, learning.user_id),
        (scope.agent_id, learning.agent_id),
    ):
        if axis_value is not None and axis_value != (learning_value or ""):
            return False
    return learning.status == "active"


def _memory_in_scope(memory: EpisodicMemory, scope: ScopeSelection) -> bool:
    for axis_value, memory_value in (
        (scope.org_id, memory.org_id),
        (scope.team_id, memory.team_id),
        (scope.user_id, memory.user_id),
        (scope.agent_id, memory.agent_id),
        (scope.project_id, memory.project_id),
    ):
        if axis_value is not None and axis_value != (memory_value or ""):
            return False
    return not memory.deleted


class DurableMemorySource:
    """Projects episodic memories and learnings into the working graph.

    Both inputs are the engine's existing durable store protocols; this class
    is a read-only adapter. Memories keep their tier/weight in node metadata
    and their Run/NodeRun/Attempt provenance in :class:`CanonicalRef`, which is
    the transcript linkage Dreaming needs to tell durable-memory candidates
    from merely available history (#301, #1047).
    """

    def __init__(
        self,
        *,
        episodic: EpisodicStore | None = None,
        learnings: LearningStore | None = None,
        scope: ScopeSelection | None = None,
    ) -> None:
        self._episodic = episodic
        self._learnings = learnings
        self._scope = scope or ScopeSelection()

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot:
        snapshot = WorkingMemorySnapshot(workspace_id=workspace_id)
        if self._episodic is not None:
            await self._collect_memories(workspace_id, snapshot, limit)
        if self._learnings is not None:
            await self._collect_learnings(workspace_id, snapshot, limit)
        return snapshot

    async def _collect_memories(
        self, workspace_id: str, snapshot: WorkingMemorySnapshot, limit: int
    ) -> None:
        assert self._episodic is not None
        memories = await self._episodic.list_by_scope(
            agent_id=self._scope.agent_id,
            user_id=self._scope.user_id,
            team_id=self._scope.team_id,
            org_id=self._scope.org_id,
            project_id=self._scope.project_id,
            limit=limit,
        )
        for memory in memories:
            if not _memory_in_scope(memory, self._scope):
                continue
            snapshot.nodes.append(_memory_node(workspace_id, memory))
            run_edge = _produced_during_edge(
                workspace_id,
                src=node_id_for(NodeKind.MEMORY, memory.memory_id),
                run_id=memory.run_id,
            )
            if run_edge is not None:
                snapshot.edges.append(run_edge)
            if self._scope.project_id and memory.project_id == self._scope.project_id:
                snapshot.edges.append(
                    _project_edge(
                        workspace_id,
                        snapshot,
                        memory.project_id,
                        node_id_for(NodeKind.MEMORY, memory.memory_id),
                    )
                )

    async def _collect_learnings(
        self, workspace_id: str, snapshot: WorkingMemorySnapshot, limit: int
    ) -> None:
        assert self._learnings is not None
        learnings = await self._learnings.list_all(org_id=self._scope.org_id or "", limit=limit)
        for learning in learnings:
            if not _learning_in_scope(learning, self._scope):
                continue
            canonical_id = str(learning.id) if learning.id is not None else ""
            if not canonical_id:
                continue
            snapshot.nodes.append(_learning_node(workspace_id, learning, canonical_id))
            run_edge = _produced_during_edge(
                workspace_id,
                src=node_id_for(NodeKind.LEARNING, canonical_id),
                run_id=learning.run_id,
            )
            if run_edge is not None:
                snapshot.edges.append(run_edge)


def _memory_node(workspace_id: str, memory: EpisodicMemory) -> WorkingGraphNode:
    ref = CanonicalRef(
        workspace_id=workspace_id,
        memory_id=memory.memory_id,
        run_id=memory.run_id,
        node_run_id=memory.node_run_id,
        attempt_id=memory.attempt_id,
        project_id=memory.project_id,
        user_id=memory.user_id or "",
        org_id=memory.org_id,
        team_id=memory.team_id,
    )
    return WorkingGraphNode(
        node_id=node_id_for(NodeKind.MEMORY, memory.memory_id),
        kind=NodeKind.MEMORY,
        label=memory.content.split("\n", 1)[0][:120] or memory.memory_id,
        content=memory.content,
        workspace_id=workspace_id,
        ref=ref,
        metadata={
            "tier": memory.tier.value,
            "weight": memory.weight,
            "source": memory.source,
            "scope": memory.scope.value
            if isinstance(memory.scope, MemoryScope)
            else str(memory.scope),
        },
    )


def _learning_node(workspace_id: str, learning: Learning, canonical_id: str) -> WorkingGraphNode:
    ref = CanonicalRef(
        workspace_id=workspace_id,
        learning_id=learning.id,
        run_id=learning.run_id,
        node_run_id=learning.node_run_id,
        attempt_id=learning.attempt_id,
        user_id=learning.user_id or "",
        org_id=learning.org_id,
        team_id=learning.team_id,
    )
    return WorkingGraphNode(
        node_id=node_id_for(NodeKind.LEARNING, canonical_id),
        kind=NodeKind.LEARNING,
        label=learning.learning.split("\n", 1)[0][:120] or f"learning:{canonical_id}",
        content=learning.learning,
        workspace_id=workspace_id,
        ref=ref,
        metadata={
            "category": learning.category,
            "tool_name": learning.tool_name,
            "hit_count": learning.hit_count,
        },
    )


def _produced_during_edge(workspace_id: str, *, src: str, run_id: str) -> WorkingGraphEdge | None:
    if not run_id:
        return None
    dst = node_id_for(NodeKind.RUN, run_id)
    return WorkingGraphEdge(
        edge_id=f"{src}->{dst}",
        workspace_id=workspace_id,
        src_node_id=src,
        dst_node_id=dst,
        relation=EdgeRelation.PRODUCED_DURING,
    )


def _project_edge(
    workspace_id: str, snapshot: WorkingMemorySnapshot, project_id: str, src: str
) -> WorkingGraphEdge:
    dst = node_id_for(NodeKind.PROJECT, project_id)
    if not any(node.node_id == dst for node in snapshot.nodes):
        snapshot.nodes.append(
            WorkingGraphNode(
                node_id=dst,
                kind=NodeKind.PROJECT,
                label=f"project {project_id}",
                workspace_id=workspace_id,
                ref=CanonicalRef(workspace_id=workspace_id, project_id=project_id),
            )
        )
    return WorkingGraphEdge(
        edge_id=f"{src}->{dst}",
        workspace_id=workspace_id,
        src_node_id=src,
        dst_node_id=dst,
        relation=EdgeRelation.BELONGS_TO_PROJECT,
    )


class ArtifactHistorySource:
    """Projects durable artifact versions (accepted, rejected, …) into the graph.

    Every version becomes its own node carrying ``artifact_id`` +
    ``artifact_version`` + ``status`` — enough for the Workspace Agent to
    retrieve prior accepted/rejected work and user corrections from durable
    artifact history, with references resolving back to the record of truth.
    """

    def __init__(self, artifacts: ArtifactSource) -> None:
        self._artifacts = artifacts

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot:
        snapshot = WorkingMemorySnapshot(workspace_id=workspace_id)
        versions = await self._artifacts.versions_for_workspace(workspace_id, limit=limit)
        lineage: dict[str, str] = {}
        for version in versions:
            node_id = node_id_for(NodeKind.ARTIFACT, f"{version.artifact_id}:v{version.version}")
            ref = CanonicalRef(
                workspace_id=workspace_id,
                artifact_id=version.artifact_id,
                artifact_version=version.version,
                run_id=version.run_id,
                node_run_id=version.node_run_id,
                project_id=version.project_id,
                goal_id=version.goal_id,
                persona_id=version.persona_id,
                user_id=version.user_id,
            )
            snapshot.nodes.append(
                WorkingGraphNode(
                    node_id=node_id,
                    kind=NodeKind.ARTIFACT,
                    label=f"{version.kind or 'artifact'} {version.artifact_id} v{version.version} ({version.status})",
                    content=version.summary,
                    workspace_id=workspace_id,
                    ref=ref,
                    metadata={"status": version.status},
                )
            )
            produced = _produced_during_edge(workspace_id, src=node_id, run_id=version.run_id)
            if produced is not None:
                snapshot.edges.append(produced)
            anchor = lineage.get(version.artifact_id)
            if anchor is None:
                lineage[version.artifact_id] = node_id
            else:
                snapshot.edges.append(
                    WorkingGraphEdge(
                        edge_id=f"{node_id}->{anchor}",
                        workspace_id=workspace_id,
                        src_node_id=node_id,
                        dst_node_id=anchor,
                        relation=EdgeRelation.VERSION_OF,
                    )
                )
        return snapshot


class RunProvenanceHydrationSource:
    """Projects canonical Run provenance (Goal/Graph linkage) into the graph."""

    def __init__(self, runs: RunProvenanceSource) -> None:
        self._runs = runs

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot:
        snapshot = WorkingMemorySnapshot(workspace_id=workspace_id)
        runs = await self._runs.recent_runs(workspace_id, limit=limit)
        for run in runs:
            node_id = node_id_for(NodeKind.RUN, run.run_id)
            snapshot.nodes.append(
                WorkingGraphNode(
                    node_id=node_id,
                    kind=NodeKind.RUN,
                    label=f"run {run.run_id}",
                    content=run.summary,
                    workspace_id=workspace_id,
                    ref=CanonicalRef(
                        workspace_id=workspace_id,
                        run_id=run.run_id,
                        goal_id=run.goal_id,
                        project_id=run.project_id,
                        persona_id=run.persona_id,
                    ),
                    metadata={
                        "status": run.status,
                        "graph_id": run.graph_id,
                        "parent_run_id": run.parent_run_id,
                    },
                )
            )
            if run.parent_run_id:
                parent = node_id_for(NodeKind.RUN, run.parent_run_id)
                snapshot.edges.append(
                    WorkingGraphEdge(
                        edge_id=f"{node_id}->{parent}",
                        workspace_id=workspace_id,
                        src_node_id=node_id,
                        dst_node_id=parent,
                        relation=EdgeRelation.FOLLOWS,
                    )
                )
        return snapshot


class TerminologyHydrationSource:
    """Projects Workspace terminology into the graph as anchor nodes."""

    def __init__(self, terms: TerminologySource) -> None:
        self._terms = terms

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot:
        snapshot = WorkingMemorySnapshot(workspace_id=workspace_id)
        records = await self._terms.terms_for_workspace(workspace_id, limit=limit)
        for record in records:
            snapshot.nodes.append(
                WorkingGraphNode(
                    node_id=node_id_for(NodeKind.TERM, record.term),
                    kind=NodeKind.TERM,
                    label=record.term,
                    content=record.definition,
                    workspace_id=workspace_id,
                    ref=CanonicalRef(workspace_id=workspace_id, project_id=record.project_id),
                )
            )
        return snapshot
