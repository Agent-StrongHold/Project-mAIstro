"""Graph execution obtains its Run identity from the canonical store (#44).

The first of the three construction sites ADR-082826-d9f5 converges. Before
this, `_new_run` minted a `Run` in memory and the whole `DurableRunRecord` was
handed to a store that had never seen it — which is why `GET /v1/runs/{id}`
could not find a graph Run, and why an adapter could not have fixed it: every
id existed before the canonical store was involved, so persisting the record
would have meant the store accepting identities its caller assigned first.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    InMemoryDurableRunStore,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus


class _StepIn(BaseModel):
    pass


class _StepOut(BaseModel):
    text: str = "done"


class _Step(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_identity.step"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        return _StepOut()


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-canonical")
    project = await projects.create(
        workspace_id="ws-canonical", parent_project_id=root.project_id, name="Graphs"
    )
    return InMemoryRunStore(project_store=projects), "ws-canonical", project.project_id


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type=_Step.kind)],
    )


def _resolver(node_id: str, graph: Any) -> Any:
    return _Step()


async def test_a_graph_run_is_findable_in_the_canonical_store() -> None:
    """The symptom #44 exists to remove: graph Runs invisible to the spine."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    canonical = await run_store.get_run(record.run.run_id)
    assert canonical is not None, "the Run the graph executed is in the canonical store"
    assert canonical.workspace_id == workspace_id
    assert canonical.project_id == project_id
    assert canonical.provenance["executor"] == "durable_graph"


async def test_the_identity_is_the_stores_not_the_records() -> None:
    """The record's `run` is a projection of a row that already exists, rather
    than an id minted here and persisted afterwards."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    listed = await run_store.list_by_status(RunStatus.RUNNING, limit=100)
    listed += await run_store.list_by_status(RunStatus.COMPLETED, limit=100)
    assert record.run.run_id in {run.run_id for run in listed}


async def test_without_a_canonical_store_the_previous_behaviour_is_unchanged() -> None:
    """`run_store` is opt-in: a caller with no spine wired still runs, exactly
    as it did before, rather than failing to start."""
    workspace_id, project_id = "ws-none", "project-none"

    record = await run_durable_graph(
        Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="one step",
            nodes=[Node(node_id="step", node_type=_Step.kind)],
        ),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
    )

    assert record.run.run_id
    assert record.status is RunStatus.COMPLETED


async def test_a_pinned_run_id_still_wins_over_canonical_creation() -> None:
    """An already-admitted Run being executed must not get a second identity —
    creating one is the duplicate this convergence removes."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_id="pinned-run-1",
        run_store=run_store,
    )

    assert record.run.run_id == "pinned-run-1"
    assert await run_store.get_run("pinned-run-1") is None


async def test_frontier_node_runs_are_findable_in_the_canonical_store() -> None:
    """The second construction site. A NodeRun minted in the record alone is a
    node nothing outside this record can see — the same defect as the Run."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    canonical = await run_store.list_node_runs(record.run_id)
    assert [item.node_run_id for item in canonical] == [
        item.node_run_id for item in record.node_runs
    ]
    assert [item.node_id for item in canonical] == ["step"]


async def test_attempts_are_findable_in_the_canonical_store() -> None:
    """The third site. Physical execution history is the canonical store's."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    assert record.attempts, "the Attempt firewall ran at least one physical try"
    for node_run in record.node_runs:
        canonical = await run_store.list_attempts(node_run.node_run_id)
        mirrored = [item for item in record.attempts if item.node_run_id == node_run.node_run_id]
        assert [item.attempt_id for item in canonical] == [item.attempt_id for item in mirrored]


async def test_a_settled_attempt_does_not_read_differently_per_store() -> None:
    """Identity without lifecycle would be worse than neither: a canonical row
    frozen at CREATED while the record calls the same Attempt finished is a
    divergence a global lease sweep would then act on."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    for attempt in record.attempts:
        canonical = await run_store.get_attempt(attempt.attempt_id)
        assert canonical is not None
        assert canonical.status is attempt.status


async def test_without_a_canonical_store_nothing_reaches_the_spine() -> None:
    """The opt-in holds all the way down: no `run_store`, no canonical rows,
    and the record carries the whole execution exactly as it did before."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
    )

    assert record.node_runs and record.attempts
    assert await run_store.get_run(record.run_id) is None


async def test_the_run_and_its_node_reach_their_terminal_status_canonically() -> None:
    """Identity without lifecycle is a row that lies. A canonical Run left
    RUNNING after the graph finished is exactly as wrong as one that is
    missing, and a lease sweep would act on it."""
    run_store, workspace_id, project_id = await _spine()

    record = await run_durable_graph(
        _graph(workspace_id, project_id),
        store=InMemoryDurableRunStore(),
        node_resolver=_resolver,
        run_store=run_store,
    )

    run = await run_store.get_run(record.run_id)
    assert run is not None
    assert run.status is record.run.status is RunStatus.COMPLETED

    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.status for item in node_runs] == [RunStatus.COMPLETED]
    assert node_runs[0].accepted_outcome is not None, (
        "the canonical NodeRun keeps the physical evidence its outcome was accepted on"
    )


class _AskIn(BaseModel):
    question: str = "Continue?"


class _AskOut(BaseModel):
    text: str = ""


class _Ask(BaseNode[_AskIn, _AskOut]):
    kind: ClassVar[str] = "test.canonical_identity.ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _AskIn
    output_schema: ClassVar[type[BaseModel]] = _AskOut

    async def _execute(self, inputs: _AskIn, ctx: NodeContext) -> _AskOut:
        answered = ((ctx.metadata or {}).get("hitl_answers") or {}).get(ctx.node_id)
        if answered is not None:
            return _AskOut(text=str(answered.get("answer") or ""))
        pause_until("awaiting_human_answer", metadata={"question": inputs.question})
        return _AskOut(text="UNREACHABLE")


async def test_a_node_answered_out_of_a_pause_walks_the_statuses_it_must() -> None:
    """The canonical row is behind by more than one edge here: it paused, and
    the answer moved the record to QUEUED without the store seeing it. Jumping
    PAUSED straight to COMPLETED is an edge the lifecycle table does not have,
    so the write-back walks the gap instead of demanding one."""
    run_store, workspace_id, project_id = await _spine()
    store = InMemoryDurableRunStore()
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="ask once",
        nodes=[Node(node_id="ask", node_type=_Ask.kind)],
    )

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, _graph: _Ask(),
        run_store=run_store,
    )
    assert paused.status is RunStatus.PAUSED
    canonical = await run_store.get_run(paused.run_id)
    assert canonical is not None and canonical.status is RunStatus.PAUSED

    await store.submit_hitl_answer(paused.run_id, "ask", {"answer": "yes"})
    resumed = await resume_durable_graph(
        paused.run_id,
        store=store,
        node_resolver=lambda node_id, _graph: _Ask(),
        run_store=run_store,
    )

    assert resumed.status is RunStatus.COMPLETED
    settled = await run_store.get_run(paused.run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED
    node_runs = await run_store.list_node_runs(paused.run_id)
    assert [item.status for item in node_runs] == [RunStatus.COMPLETED]


async def test_resuming_a_pre_convergence_record_takes_the_old_path() -> None:
    """A record written before the convergence carries a Run the canonical
    store never saw. Minting its NodeRuns there would attach them to nothing,
    so it keeps running rather than failing on resume."""
    run_store, workspace_id, project_id = await _spine()
    store = InMemoryDurableRunStore()
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="ask once",
        nodes=[Node(node_id="ask", node_type=_Ask.kind)],
    )

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, _graph: _Ask(),
    )
    await store.submit_hitl_answer(paused.run_id, "ask", {"answer": "yes"})

    resumed = await resume_durable_graph(
        paused.run_id,
        store=store,
        node_resolver=lambda node_id, _graph: _Ask(),
        run_store=run_store,
    )

    assert resumed.status is RunStatus.COMPLETED
    assert await run_store.get_run(paused.run_id) is None


class _Boom(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.canonical_identity.boom"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        raise ValueError("intentional test failure")


async def test_a_failed_node_settles_canonically_too() -> None:
    """Failure is the half a mirror is most tempting to skip and least safe to:
    a canonical Run left RUNNING because its graph failed is work nothing will
    ever recover, since recovery only looks at what the store says is open."""
    run_store, workspace_id, project_id = await _spine()
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="one bad step",
        nodes=[Node(node_id="boom", node_type=_Boom.kind)],
    )

    record = await run_durable_graph(
        graph,
        store=InMemoryDurableRunStore(),
        node_resolver=lambda node_id, _graph: _Boom(),
        run_store=run_store,
    )

    assert record.status is RunStatus.FAILED
    run = await run_store.get_run(record.run_id)
    assert run is not None and run.status is RunStatus.FAILED
    node_runs = await run_store.list_node_runs(record.run_id)
    assert [item.status for item in node_runs] == [RunStatus.FAILED]
    outcome = node_runs[0].accepted_outcome
    assert outcome is not None, "failure is accepted evidence too, not an absence of it"
    assert outcome.attempt_result.attempt_id in {item.attempt_id for item in record.attempts}
    assert "intentional test failure" in str(node_runs[0].error)
