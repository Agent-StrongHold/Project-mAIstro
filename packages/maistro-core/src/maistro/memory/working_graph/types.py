"""Working-memory graph types (#776, ADR-082226-5104).

The working graph is a **disposable projection** of durable memory, never an
authority: PostgreSQL + pgvector remain the durable system of record, and a
working graph may be discarded and rebuilt from that record without changing
any durable truth. Everything this module models therefore carries the
canonical identities the projection was hydrated from, so a consumer (the
persistent Workspace Agent, #773/#777, Dreaming under #301) can always resolve
a working node back to durable truth instead of trusting the projection.

Isolation is structural: every node and edge is stamped with the
``workspace_id`` it belongs to, and the graph backends refuse records for any
other Workspace. One Workspace, one graph — a traversal in one Workspace
cannot wander into another's working memory because the data is simply absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NodeKind(StrEnum):
    """What kind of durable record a working node was hydrated from."""

    MEMORY = "memory"
    LEARNING = "learning"
    ARTIFACT = "artifact"
    RUN = "run"
    TERM = "term"
    PROJECT = "project"


class EdgeRelation(StrEnum):
    """Typed relations between working nodes.

    Deliberately shallow and typed, like the durable relationship tables
    (ADR-082226-5104 §3): the working graph is an associative projection of
    the same records, not a free-form knowledge base.
    """

    #: memory/learning/artifact was produced during that Run.
    PRODUCED_DURING = "produced_during"
    #: child Run follows its parent Run.
    FOLLOWS = "follows"
    #: memory/learning belongs to a Project.
    BELONGS_TO_PROJECT = "belongs_to_project"
    #: an artifact version is one version of its artifact lineage.
    VERSION_OF = "version_of"


class WorkingMemoryHealth(StrEnum):
    """The honest state of one Workspace's working graph.

    Read paths never silently pretend memory is available: a broken or
    partially hydrated projection reports DEGRADED or UNAVAILABLE, and
    consumers must surface that instead of a confident blank.
    """

    #: Not yet hydrated; no graph-backed context has been materialised.
    COLD = "cold"
    #: Hydrated from durable records and serving.
    HEALTHY = "healthy"
    #: Serving, but at least one hydration source or backend op failed, so the
    #: projection may be stale or partial relative to durable truth.
    DEGRADED = "degraded"
    #: The projection cannot answer at all. Durable truth is unaffected.
    UNAVAILABLE = "unavailable"


class WorkingMemoryError(Exception):
    """Base class for working-memory refusals."""


class BackendUnavailableError(WorkingMemoryError):
    """The configured graph backend cannot be used (e.g. missing package)."""


class ForeignWorkspaceError(WorkingMemoryError, PermissionError):
    """A record or query for another Workspace reached this graph."""


@dataclass
class CanonicalRef:
    """Canonical durable identities a working node was hydrated from.

    Every field is an id in the durable system of record (Workspace, Project,
    Persona, Goal, Run, NodeRun, Attempt, memory, artifact), not a working-graph
    local id — that is what lets a consumer resolve durable truth and lets
    Dreaming tell durable-memory candidates from merely available history (#64,
    #776, #1047).
    """

    workspace_id: str
    memory_id: str = ""
    learning_id: int | None = None
    artifact_id: str = ""
    artifact_version: str = ""
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
    project_id: str = ""
    persona_id: str = ""
    goal_id: str = ""
    user_id: str = ""
    org_id: str = ""
    team_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "workspace_id": self.workspace_id,
                "memory_id": self.memory_id,
                "learning_id": self.learning_id,
                "artifact_id": self.artifact_id,
                "artifact_version": self.artifact_version,
                "run_id": self.run_id,
                "node_run_id": self.node_run_id,
                "attempt_id": self.attempt_id,
                "project_id": self.project_id,
                "persona_id": self.persona_id,
                "goal_id": self.goal_id,
                "user_id": self.user_id,
                "org_id": self.org_id,
                "team_id": self.team_id,
            }.items()
            if value not in ("", None)
        }


@dataclass
class WorkingGraphNode:
    """One node of a Workspace's working graph.

    ``node_id`` is graph-local and namespaced by kind
    (``f"{kind}:{canonical id}"``); ``ref`` carries the canonical durable
    identities. ``durable`` marks nodes hydrated from authoritative records
    (the only kind hydration produces); a working-only, tentative node is a
    #301/M4 concern and must stay distinguishable from durable candidates.
    """

    node_id: str
    kind: NodeKind
    label: str
    workspace_id: str
    ref: CanonicalRef
    content: str = ""
    durable: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkingGraphEdge:
    """One typed edge of a Workspace's working graph."""

    edge_id: str
    workspace_id: str
    src_node_id: str
    dst_node_id: str
    relation: EdgeRelation
    ref: CanonicalRef | None = None
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class GraphContext:
    """Graph-backed context returned to the Workspace Agent.

    ``health`` is part of the answer, not a side channel: a DEGRADED or
    UNAVAILABLE context must be surfaced as such by consuming products, never
    rendered as confident memory.
    """

    workspace_id: str
    query: str
    nodes: list[WorkingGraphNode] = field(default_factory=list)
    edges: list[WorkingGraphEdge] = field(default_factory=list)
    health: WorkingMemoryHealth = WorkingMemoryHealth.HEALTHY
    degraded_reason: str = ""

    def to_text(self, *, max_content_chars: int = 240) -> str:
        """Render the context as a prompt-ready block.

        Every line keeps its canonical references, so a model quoting this
        block is still quoting durable truth rather than graph-local guesses.
        """
        lines: list[str] = [f"workspace-memory: workspace={self.workspace_id}"]
        if self.health is not WorkingMemoryHealth.HEALTHY:
            reason = self.degraded_reason or "working memory is not fully available"
            lines.append(f"memory-health: {self.health.value} ({reason})")
        for node in self.nodes:
            provenance = ", ".join(
                f"{key}={value}" for key, value in sorted(node.ref.to_dict().items())
            )
            content = node.content.strip().replace("\n", " ")
            if len(content) > max_content_chars:
                content = content[: max_content_chars - 1] + "…"
            lines.append(f"- [{node.kind.value}] {node.label}: {content} ({provenance})")
        return "\n".join(lines)


@dataclass
class WorkingMemoryStatus:
    """Operational status of one Workspace's working graph."""

    workspace_id: str
    health: WorkingMemoryHealth
    backend: str
    node_count: int = 0
    edge_count: int = 0
    hydrated: bool = False
    last_hydrated_at: datetime | None = None
    last_error: str = ""


def node_id_for(kind: NodeKind, canonical_id: str) -> str:
    """The namespaced, graph-local node id for one durable record."""
    return f"{kind.value}:{canonical_id}"
