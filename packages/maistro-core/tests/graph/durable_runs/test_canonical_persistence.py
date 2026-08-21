"""Integrity tests for the canonical durable graph persistence envelope."""

from __future__ import annotations

import pytest

from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import NodeRun

from .._canonical_helpers import durable_record, graph_from_dag, run_at_status


def test_active_frontier_must_belong_to_run_graph_snapshot() -> None:
    with pytest.raises(ValueError, match="active graph frontier"):
        durable_record(
            {"id": "g", "nodes": [{"id": "n1"}], "edges": []},
            run_id="r1",
            active_node_id="missing",
        )


def test_node_runs_must_belong_to_persisted_run() -> None:
    graph = graph_from_dag({"id": "g", "nodes": [{"id": "n1"}], "edges": []})
    run = run_at_status(graph, run_id="r1")
    state = GraphExecutionState(run_id="r1", active_node_ids=("n1",))

    with pytest.raises(ValueError, match="every NodeRun must belong"):
        DurableRunRecord(
            run=run,
            graph_state=state,
            node_runs=(NodeRun(run_id="other", node_id="n1", ordinal=1),),
        )


def test_node_run_ordinals_must_be_consecutive_persistence_order() -> None:
    graph = graph_from_dag({"id": "g", "nodes": [{"id": "n1"}], "edges": []})
    run = run_at_status(graph, run_id="r1")
    state = GraphExecutionState(run_id="r1", active_node_ids=("n1",))

    with pytest.raises(ValueError, match="ordinals must be consecutive"):
        DurableRunRecord(
            run=run,
            graph_state=state,
            node_runs=(NodeRun(run_id="r1", node_id="n1", ordinal=2),),
        )
