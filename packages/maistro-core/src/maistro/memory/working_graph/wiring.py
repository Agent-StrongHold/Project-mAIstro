"""Deployment wiring for the per-Workspace working-memory seam (#776).

The seam's own modules (`hydration`, `store`, `manager`, `backend`) are
deployment-neutral: they refuse to invent a mapping from a canonical Workspace
to durable scope axes, because that mapping belongs to whoever owns the
durable stores. This module is that owner's half — the adapters the engine's
own Container wires, so the working graph is reachable from production entry
points rather than a library surface only tests import.

What the engine can honestly project today:

- **Episodic memories**, scoped to the Workspace's own Project tree. Every
  Project in the canonical scope store carries the ``workspace_id`` it belongs
  to, so "the memories of this Workspace" has exactly one durable meaning:
  memories whose ``project_id`` sits in that Workspace's tree. Anything else
  (an org- or user-scoped read) would silently hydrate another Workspace's
  records into this one's graph, which is the leak the isolation acceptance
  criterion exists to forbid.
- **Run provenance**, read through the Run store's own ``workspace_id`` axis —
  the canonical Goal -> Graph -> Run spine records, with their graph, project,
  persona and parent-Run linkage.

What is deliberately **not** wired yet, and why:

- **Learnings.** ``LearningStore.list_all`` filters by ``org_id`` only, and the
  canonical Workspace model has no org axis, so no workspace-honest filter
  exists. Hydrating them unfiltered would give every Workspace every other
  Workspace's corrections in its graph. They join when a durable axis does.
- **Artifact versions and terminology.** The engine has no durable store for
  either yet; the seam's source ports are ready for #773/#777's stores, and
  the hydration paths are exercised against the port contracts in the seam
  tests.

Everything here is read-only over the durable stores and never grants
authorization: the block a chat turn receives is projected from the Run's own
Workspace, and a degraded projection travels to the agent as an explicit
health state rather than as silence (ADR-082226-5104 §5, #776).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Final

from maistro.memory.working_graph.hydration import (
    DurableMemorySource,
    RunProvenanceHydrationSource,
    RunProvenanceRecord,
    ScopeSelection,
    WorkingMemorySnapshot,
    WorkingMemorySource,
)
from maistro.memory.working_graph.manager import WorkspaceWorkingMemoryManager
from maistro.memory.working_graph.types import GraphContext
from maistro.projects.scope import ProjectNotFound
from maistro.projects.scope_store import ProjectScopeStore
from maistro.protocols.memory import EpisodicStore
from maistro.runs.model import Run, RunStatus
from maistro.runs.store import RunStore

#: Upper bound on how much of one Workspace's Project tree one hydration pass
#: walks. The tree is the Workspace's own scope, but an unbounded walk would
#: make the first chat turn after eviction pay for the whole tree; the bound
#: keeps lazy hydration lazy. Deepest-first BFS ordering keeps the bound
#: deterministic.
MAX_PROJECTS_PER_HYDRATION: Final = 32

#: The Run statuses one hydration pass projects into the working graph. The
#: statuses a Workspace Agent reconciles against — admitted work, what is in
#: flight, what landed, what broke. Queries stay bounded per status; the
#: union is capped at the caller's limit.
_PROVENANCE_STATUSES: Final = (
    RunStatus.CREATED,
    RunStatus.RUNNING,
    RunStatus.COMPLETED,
    RunStatus.FAILED,
)

logger = logging.getLogger(__name__)


class WorkspaceProjectMemorySource:
    """The episodic memories of one Workspace's own Project tree.

    Implements the seam's :class:`WorkingMemorySource` protocol by resolving
    the Workspace's Root Project, walking its bounded descendant tree, and
    reusing :class:`DurableMemorySource` per Project — one scope axis per read,
    so a memory hydrates only into the Workspace its Project belongs to. A
    Workspace with no Root Project (an unknown or purged Workspace id) has no
    durable scope to project, and hydrates to an empty snapshot rather than an
    error: the honest answer to "what does this Workspace remember" when there
    is no Workspace is "nothing", not an outage.
    """

    def __init__(
        self,
        *,
        episodic: EpisodicStore,
        projects: ProjectScopeStore,
        max_projects: int = MAX_PROJECTS_PER_HYDRATION,
    ) -> None:
        self._episodic = episodic
        self._projects = projects
        self._max_projects = max_projects

    async def collect(self, workspace_id: str, *, limit: int) -> WorkingMemorySnapshot:
        merged = WorkingMemorySnapshot(workspace_id=workspace_id)
        for project_id in await self._workspace_project_ids(workspace_id):
            source = DurableMemorySource(
                episodic=self._episodic,
                scope=ScopeSelection(project_id=project_id),
            )
            snapshot = await source.collect(workspace_id, limit=limit)
            merged.nodes.extend(snapshot.nodes)
            merged.edges.extend(snapshot.edges)
            if len(merged.nodes) >= limit:
                break
        # One scope read per Project is bounded by the tree walk; honour the
        # caller's cap on the merge as well, so the total stays the bound the
        # store asked for.
        return WorkingMemorySnapshot(
            workspace_id=workspace_id,
            nodes=merged.nodes[:limit],
            edges=merged.edges,
        )

    async def _workspace_project_ids(self, workspace_id: str) -> list[str]:
        """The Workspace's Root Project id, then descendants, breadth-first.

        Bounded by ``max_projects`` total. A Project outside the tree cannot
        appear: children are only listed from ids already in the tree, and the
        scope store refuses cross-Workspace parents.
        """
        try:
            root = await self._projects.root_for_workspace(workspace_id)
        except ProjectNotFound:
            return []
        ids = [root.project_id]
        frontier = [root.project_id]
        while frontier and len(ids) < self._max_projects:
            current = frontier.pop(0)
            children = await self._projects.list_children(current)
            for child in children:
                if len(ids) >= self._max_projects:
                    break
                ids.append(child.project_id)
                frontier.append(child.project_id)
        return ids


class WorkspaceRunStoreProvenanceSource:
    """Canonical Run provenance for one Workspace, via the Run store.

    Implements the seam's :class:`RunProvenanceSource` port over
    ``RunStore.list_by_status``'s own ``workspace_id`` axis — the same axis
    admission and the scoped product reads route on, so the projection can
    never widen what the durable store would answer.

    M1 product-local projection: Run
    M1 product-local projection: Workspace

    This is not the canonical Run or Workspace model: it projects one Run's
    admission provenance into the working-memory domain's ``RunProvenanceRecord``
    for the Workspace the Run already belongs to, and holds no durable truth of
    either — every canonical Run and Workspace fact stays in the Run store and
    the workspace scope stores.
    """

    def __init__(
        self,
        *,
        runs: RunStore,
        statuses: Sequence[RunStatus] = _PROVENANCE_STATUSES,
    ) -> None:
        self._runs = runs
        self._statuses = tuple(statuses)

    async def recent_runs(self, workspace_id: str, *, limit: int) -> list[RunProvenanceRecord]:
        records: list[RunProvenanceRecord] = []
        for status in self._statuses:
            runs = await self._runs.list_by_status(status, limit=limit, workspace_id=workspace_id)
            records.extend(_provenance_record(run) for run in runs)
        return records[:limit]


def _provenance_record(run: Run) -> RunProvenanceRecord:
    """The canonical provenance one Run contributes (#64).

    ``goal_id`` lives in the Run's admission provenance when a Goal named it;
    a Run admitted outside a Goal contributes no Goal identity rather than an
    invented one.
    """
    return RunProvenanceRecord(
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        status=run.status.value if isinstance(run.status, RunStatus) else str(run.status),
        goal_id=str(run.provenance.get("goal_id", "") or ""),
        graph_id=run.graph.graph_id,
        project_id=run.project_id,
        persona_id=run.persona_id or "",
        parent_run_id=run.parent_run_id or "",
        summary="",
    )


def build_workspace_working_memory(
    *,
    episodic: EpisodicStore,
    projects: ProjectScopeStore,
    runs: RunStore,
    max_active_graphs: int = 64,
) -> WorkspaceWorkingMemoryManager:
    """The Container's working-memory manager: one graph per active Workspace.

    Sources are the engine's own durable stores behind the adapters above; the
    default embedded backend keeps each Workspace's graph a separate
    in-process projection, which is the isolation the acceptance criteria
    demand and LadybugDB's adapter will replace per-Workspace in kind
    (ADR-082226-5104 §5).
    """
    sources: list[WorkingMemorySource] = [
        WorkspaceProjectMemorySource(episodic=episodic, projects=projects),
        RunProvenanceHydrationSource(WorkspaceRunStoreProvenanceSource(runs=runs)),
    ]
    return WorkspaceWorkingMemoryManager(sources=sources, max_active_graphs=max_active_graphs)


_BLOCK_LIMIT: Final = 6
_QUERY_LIMIT: Final = 8
_CONTEXT_HOPS: Final = 1


def render_working_memory_block(context: GraphContext) -> str:
    """Render one :class:`GraphContext` as the chat turn's system context block.

    Health is part of the rendering, never smoothed over: a DEGRADED or
    UNAVAILABLE projection says so in the block, so the agent sees the state
    of its working memory instead of a confident blank (#776). Nodes keep
    their canonical durable identities, so anything the model repeats about
    prior work carries the ids that resolve to the system of record.
    """
    lines = [
        f'<maistro:working-memory workspace="{context.workspace_id}" '
        f'health="{context.health.value}">'
    ]
    if context.degraded_reason:
        lines.append(
            f"Working memory is {context.health.value}: {context.degraded_reason} "
            "(durable memory remains the system of record)."
        )
    for node in context.nodes[:_BLOCK_LIMIT]:
        entry = f"- [{node.kind.value}] {node.label}"
        if node.content:
            entry += f" — {node.content}"
        lines.append(entry)
        refs = node.ref.to_dict()
        durable = [f"{key}={value}" for key, value in refs.items() if key != "workspace_id"]
        if durable:
            lines.append(f"  refs: {', '.join(durable)}")
    if not context.nodes and not context.degraded_reason:
        lines.append("No working-memory records matched this turn.")
    lines.append("</maistro:working-memory>")
    return "\n".join(lines)


async def working_memory_context_message(
    manager: WorkspaceWorkingMemoryManager | None,
    workspace_id: str,
    messages: Sequence[dict[str, Any]],
) -> dict[str, str] | None:
    """The working-memory system message for one chat turn, or ``None``.

    The query is the turn's own last user message; the graph read serves that
    Workspace's projection only. A container without the seam wired, a turn
    with no user text, or a blank Workspace id dispatches unchanged — the
    seam adds context, it never gates a turn.
    """
    if manager is None or not workspace_id.strip():
        return None
    query = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            query = str(message.get("content", "") or "")
            break
    if not query.strip():
        return None
    # Incremental, idempotent re-hydration before the read: a correction or
    # accepted artifact recorded durably between turns reaches the next
    # turn's context (the #776 criterion's "after hydration/update"), and a
    # backend failure here degrades the projection instead of failing the
    # turn — the read below answers UNAVAILABLE honestly either way. The
    # freshness/cost trade is the M3 floor's; tuning is #301/M4.
    try:
        graph = await manager.graph(workspace_id)
        await graph.hydrate()
    except Exception:
        logger.warning(
            "Working-memory hydration failed for workspace %s; serving degraded",
            workspace_id,
            exc_info=True,
        )
    context = await manager.context(workspace_id, query, limit=_QUERY_LIMIT, hops=_CONTEXT_HOPS)
    return {"role": "system", "content": render_working_memory_block(context)}


__all__ = [
    "MAX_PROJECTS_PER_HYDRATION",
    "WorkspaceProjectMemorySource",
    "WorkspaceRunStoreProvenanceSource",
    "build_workspace_working_memory",
    "render_working_memory_block",
    "working_memory_context_message",
]
