from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import Attempt, GraphSnapshot, NodeRun, Run


def test_durable_record_rejects_attempt_for_unpersisted_node_run() -> None:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Attempt links",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = Run(
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
    )
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    orphan = Attempt(node_run_id="missing-node-run", ordinal=1)

    with pytest.raises(ValueError, match="every Attempt must belong"):
        DurableRunRecord(
            run=run,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=("node-1",),
            ),
            node_runs=(node_run,),
            attempts=(orphan,),
        )
