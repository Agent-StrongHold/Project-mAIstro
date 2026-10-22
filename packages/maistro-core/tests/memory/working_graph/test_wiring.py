"""Container wiring: the working graph is reachable and honest (#776).

The seam modules prove hydration, isolation, rebuild and degradation at the
library level. These tests prove the deployment half — that the adapters the
Container actually wires project the right Workspace's durable records, keep
canonical identities on the way through, surface degradation instead of
silence, and never hydrate another Workspace's records into a graph.
"""

from __future__ import annotations

from typing import Any

from maistro.graph import Graph, Node
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.working_graph.hydration import RunProvenanceHydrationSource
from maistro.memory.working_graph.manager import WorkspaceWorkingMemoryManager
from maistro.memory.working_graph.types import (
    CanonicalRef,
    GraphContext,
    NodeKind,
    WorkingGraphNode,
    WorkingMemoryHealth,
)
from maistro.memory.working_graph.wiring import (
    WorkspaceProjectMemorySource,
    WorkspaceRunStoreProvenanceSource,
    build_workspace_working_memory,
    render_working_memory_block,
    working_memory_context_message,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.workspaces import InMemoryWorkspaceStore

from .conftest import WORKSPACE_A, WORKSPACE_B, make_memory


class World:
    """One deployment: real episodic + project + run stores, wired manager."""

    def __init__(self) -> None:
        self.episodic = InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        self.projects = InMemoryProjectScopeStore()
        self.workspaces = InMemoryWorkspaceStore(project_store=self.projects)
        self.runs = InMemoryRunStore(project_store=self.projects)
        self.manager = build_workspace_working_memory(
            episodic=self.episodic,
            projects=self.projects,
            runs=self.runs,
        )

    async def child_project(self, workspace_id: str, name: str) -> str:
        # The canonical create provisions the Root Project, exactly as the
        # real Workspace store does; without it nothing is in scope.
        await self.workspaces.create(
            creator_user_id=f"owner-{workspace_id}",
            name=workspace_id,
            workspace_id=workspace_id,
        )
        root = await self.projects.root_for_workspace(workspace_id)
        project = await self.projects.create(
            workspace_id=workspace_id,
            parent_project_id=root.project_id,
            name=name,
        )
        return project.project_id

    async def remember(
        self, project_id: str, content: str, *, memory_id: str, run_id: str = ""
    ) -> None:
        await self.episodic.store(
            make_memory(memory_id, content, project_id=project_id, run_id=run_id)
        )

    async def run_for(
        self,
        workspace_id: str,
        project_id: str,
        *,
        goal_id: str = "",
        parent_run_id: str | None = None,
    ) -> str:
        graph = Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="wired",
            nodes=[Node(node_id="node-1", node_type="agent")],
        )
        run = await self.runs.create_run(
            graph,
            parent_run_id=parent_run_id,
            # The store boundary requires an admitted actor (#364): a Run is
            # always created by someone, and the canonical test actor is the
            # admitted principal tests use.
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            provenance={"goal_id": goal_id} if goal_id else None,
        )
        return run.run_id


def _turn(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


async def test_block_carries_workspace_memory_with_canonical_refs() -> None:
    world = World()
    project = await world.child_project(WORKSPACE_A, "food blog")
    run_id = await world.run_for(WORKSPACE_A, project, goal_id="goal-7")
    await world.remember(
        project, "The user shoots on a Fuji X100VI", memory_id="m-1", run_id=run_id
    )

    block = await working_memory_context_message(
        world.manager, WORKSPACE_A, _turn("what camera does the user shoot on?")
    )
    assert block is not None
    assert block["role"] == "system"
    assert f'workspace="{WORKSPACE_A}"' in block["content"]
    assert 'health="healthy"' in block["content"]
    assert "Fuji X100VI" in block["content"]
    # The canonical identities survive the projection: the model can quote a
    # memory that resolves to the system of record, never a graph-local id.
    assert "memory_id=m-1" in block["content"]
    assert "goal_id=goal-7" in block["content"]


async def test_project_scoping_never_hydrates_another_workspace() -> None:
    world = World()
    project_a = await world.child_project(WORKSPACE_A, "food blog")
    await world.remember(project_a, "Fuji X100VI is the user's camera", memory_id="m-a")
    await world.child_project(WORKSPACE_B, "software")  # no memories at all

    block_b = await working_memory_context_message(
        world.manager, WORKSPACE_B, _turn("what camera does the user shoot on?")
    )
    assert block_b is not None
    # The lexical query matches the memory in A's graph — but B's projection
    # never read A's project, so the record is simply absent, and B's block
    # says so honestly instead of borrowing the hit.
    assert "Fuji" not in block_b["content"]
    assert "No working-memory records matched" in block_b["content"]
    assert "memory_id=m-a" not in block_b["content"]


async def test_unknown_workspace_hydrates_to_honest_empty_not_error() -> None:
    world = World()
    block = await working_memory_context_message(
        world.manager, "no-such-workspace", _turn("anything")
    )
    assert block is not None
    assert 'health="healthy"' in block["content"]
    assert "No working-memory records matched" in block["content"]


async def test_run_provenance_keeps_goal_and_parent_linkage() -> None:
    world = World()
    project = await world.child_project(WORKSPACE_A, "work")
    parent_id = await world.run_for(WORKSPACE_A, project, goal_id="goal-parent")
    child_id = await world.run_for(
        WORKSPACE_A, project, goal_id="goal-child", parent_run_id=parent_id
    )

    source = WorkspaceRunStoreProvenanceSource(runs=world.runs)
    records = {record.run_id: record for record in await source.recent_runs(WORKSPACE_A, limit=10)}
    child = records[child_id]
    assert child.parent_run_id == parent_id
    assert child.workspace_id == WORKSPACE_A
    # Status and graph identity are the canonical ones, not invented ones.
    assert child.status == "created"
    assert child.graph_id
    assert child.goal_id == "goal-child"

    # And the linkage survives into the graph: the child's FOLLOWS edge
    # reaches the parent Run node (the transcript linkage Dreaming reads).
    context = await world.manager.context(WORKSPACE_A, f"run {child_id}", limit=8, hops=1)
    node_ids = {node.node_id for node in context.nodes}
    assert f"run:{child_id}" in node_ids
    assert f"run:{parent_id}" in node_ids


async def test_degraded_projection_is_named_in_the_block() -> None:
    class BrokenRunStore:
        """A run store that is down: the durable read fails, loudly."""

        async def recent_runs(self, workspace_id: str, *, limit: int) -> list[Any]:
            raise RuntimeError("run store down")

    projects = InMemoryProjectScopeStore()
    episodic = InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    await workspaces.create(creator_user_id="owner-a", name=WORKSPACE_A, workspace_id=WORKSPACE_A)
    manager = WorkspaceWorkingMemoryManager(
        sources=[
            WorkspaceProjectMemorySource(episodic=episodic, projects=projects),
            RunProvenanceHydrationSource(BrokenRunStore()),
        ]
    )
    root = await projects.root_for_workspace(WORKSPACE_A)
    await episodic.store(
        make_memory("m-1", "Durable memory the store still serves", project_id=root.project_id)
    )

    block = await working_memory_context_message(manager, WORKSPACE_A, _turn("durable memory"))
    assert block is not None
    assert 'health="degraded"' in block["content"]
    assert "Working memory is degraded" in block["content"]
    assert "run store down" in block["content"]
    assert "durable memory remains the system of record" in block["content"]
    # The memory source still served: degradation is partial and named, and
    # the durable system of record is untouched.
    assert "Durable memory the store still serves" in block["content"]
    memories = await episodic.list_by_scope(project_id=root.project_id)
    assert [memory.memory_id for memory in memories] == ["m-1"]


async def test_correction_recorded_after_first_read_arrives_on_next_turn() -> None:
    world = World()
    project = await world.child_project(WORKSPACE_A, "food blog")
    await world.remember(project, "User prefers sesame oil", memory_id="m-1")
    first = await working_memory_context_message(
        world.manager, WORKSPACE_A, _turn("which oil should I use?")
    )
    assert first is not None and "sesame" in first["content"]

    # A user correction is recorded durably *between* turns.
    await world.remember(
        project, "Correction: user is allergic to sesame, use olive oil", memory_id="m-2"
    )
    second = await working_memory_context_message(
        world.manager, WORKSPACE_A, _turn("which oil should I use?")
    )
    assert second is not None
    assert "allergic to sesame" in second["content"]
    assert "memory_id=m-2" in second["content"]


async def test_discard_and_rebuild_leaves_durable_truth_intact() -> None:
    world = World()
    project = await world.child_project(WORKSPACE_A, "work")
    await world.remember(project, "The accepted design uses vector tiles", memory_id="m-1")
    before = await working_memory_context_message(world.manager, WORKSPACE_A, _turn("vector tiles"))
    assert before is not None and "vector tiles" in before["content"]

    status = await world.manager.discard(WORKSPACE_A)
    assert status.health is WorkingMemoryHealth.COLD
    memories = await world.episodic.list_by_scope(project_id=project)
    assert [memory.memory_id for memory in memories] == ["m-1"]

    after = await working_memory_context_message(world.manager, WORKSPACE_A, _turn("vector tiles"))
    assert after is not None
    assert "vector tiles" in after["content"]
    assert "memory_id=m-1" in after["content"]


async def test_context_message_is_none_without_the_seam_or_user_text() -> None:
    world = World()
    # No manager wired: a hand-built Container dispatches exactly as before.
    assert await working_memory_context_message(None, WORKSPACE_A, _turn("hi")) is None
    # Blank Workspace id: refuse to invent one.
    assert await working_memory_context_message(world.manager, "   ", _turn("hi")) is None
    # A turn with no user message carries no query to rank by.
    assert (
        await working_memory_context_message(
            world.manager, WORKSPACE_A, [{"role": "system", "content": "ping"}]
        )
        is None
    )


def test_renderer_names_health_and_limits_entries() -> None:
    def node(i: int) -> WorkingGraphNode:
        return WorkingGraphNode(
            node_id=f"memory:m-{i}",
            kind=NodeKind.MEMORY,
            label=f"memory {i}",
            content=f"content {i}",
            workspace_id="ws",
            ref=CanonicalRef(workspace_id="ws", memory_id=f"m-{i}"),
        )

    context = GraphContext(workspace_id="ws", query="q", nodes=[node(i) for i in range(10)])
    rendered = render_working_memory_block(context)
    assert rendered.count("\n- [memory]") <= 6
    assert 'health="healthy"' in rendered
    assert "memory_id=m-5" in rendered  # canonical refs travel with entries

    degraded = GraphContext(
        workspace_id="ws",
        query="q",
        health=WorkingMemoryHealth.UNAVAILABLE,
        degraded_reason="backend missing",
    )
    down = render_working_memory_block(degraded)
    assert 'health="unavailable"' in down
    assert "backend missing" in down
    assert "system of record" in down
