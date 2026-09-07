"""Adversarial trust evidence for admission-to-checkpoint launch recovery."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    InMemoryDurableRunStore,
    durable_graph_launch_provenance,
    recovery,
    run_durable_graph,
)
from maistro.graph.durable_runs.launch import (
    DURABLE_GRAPH_LAUNCH_PROVENANCE,
    launch_state_from_run,
)
from maistro.graph.execution_state import thaw_json_value
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus
from maistro.runs.store import RunIntegrityError


async def _spine() -> tuple[InMemoryRunStore, Graph]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-launch-trust")
    project = await projects.create(
        workspace_id="ws-launch-trust",
        parent_project_id=root.project_id,
        name="Launch trust",
    )
    graph = Graph(
        workspace_id="ws-launch-trust",
        project_id=project.project_id,
        name="launch trust graph",
        nodes=[Node(node_id="step", node_type="test.launch")],
    )
    return InMemoryRunStore(project_store=projects), graph


@pytest.mark.asyncio
async def test_nonempty_launch_state_must_be_durable_before_checkpoint_one() -> None:
    """A crash after admission must never make recovery invent empty inputs."""
    run_store, graph = await _spine()
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    durable = InMemoryDurableRunStore()

    with pytest.raises(RunIntegrityError, match="durable_graph_launch snapshot"):
        await run_durable_graph(
            graph,
            store=durable,
            node_resolver=lambda _node_id, _graph: None,
            run_id=admitted.run_id,
            run_store=run_store,
            inputs={"request": {"customer_id": 123}},
            blackboard_metadata={"synth_depth": 4},
        )

    assert await durable.get(admitted.run_id) is None
    assert (await run_store.get_run(admitted.run_id)).status is RunStatus.QUEUED


@pytest.mark.asyncio
async def test_corrupt_durable_launch_provenance_fails_loudly() -> None:
    """A corrupted admission snapshot must refuse recovery, not empty-launch."""
    run_store, graph = await _spine()
    corrupt_snapshots = (
        # provenance fact itself is not an object
        {DURABLE_GRAPH_LAUNCH_PROVENANCE: "corrupted"},
        # initial_inputs is not an object
        {DURABLE_GRAPH_LAUNCH_PROVENANCE: {"initial_inputs": "corrupted"}},
        # blackboard_metadata is not an object
        {
            DURABLE_GRAPH_LAUNCH_PROVENANCE: {
                "initial_inputs": {},
                "blackboard_metadata": 42,
            }
        },
    )
    for provenance in corrupt_snapshots:
        admitted = await run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            provenance=dict(provenance),
        )
        with pytest.raises(RunIntegrityError, match="durable_graph_launch"):
            launch_state_from_run(admitted)


@pytest.mark.asyncio
async def test_bootstrap_recovery_rehydrates_exact_admitted_launch_snapshot() -> None:
    run_store, graph = await _spine()
    inputs: dict[str, Any] = {"request": {"customer_id": 123, "flags": ["a", "b"]}}
    blackboard = {"synth_depth": 4, "policy": {"mode": "bounded"}}
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        provenance={
            "admission_source": "launch-trust",
            **durable_graph_launch_provenance(
                inputs=inputs,
                blackboard_metadata=blackboard,
            ),
        },
    )

    # Simulate process death after Run admission and before checkpoint 1.
    recovered = recovery._initial_queued_record(admitted)

    # GraphExecutionState freezes JSON-shaped state (nested mappings become
    # read-only proxies, lists become tuples); thaw_json_value is the public
    # accessor for the ordinary JSON view, so equality is asserted on that.
    assert thaw_json_value(recovered.graph_state.metadata["initial_inputs"]) == inputs
    assert thaw_json_value(recovered.graph_state.blackboard_snapshot["metadata"]) == blackboard

    # The snapshot is detached from caller-owned mutable data.
    inputs["request"]["flags"].append("mutated-later")
    blackboard["policy"]["mode"] = "changed-later"
    thawed_inputs = thaw_json_value(recovered.graph_state.metadata["initial_inputs"])
    thawed_metadata = thaw_json_value(recovered.graph_state.blackboard_snapshot["metadata"])
    assert thawed_inputs["request"]["flags"] == ["a", "b"]
    assert thawed_metadata["policy"]["mode"] == "bounded"
