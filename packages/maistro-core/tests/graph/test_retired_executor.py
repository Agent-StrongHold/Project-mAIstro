from __future__ import annotations

import importlib

import pytest


def test_pre_durable_executor_is_not_a_graph_public_surface() -> None:
    """Graph work enters through durable_runs, never the retired executor."""
    graph = importlib.import_module("maistro.graph")

    assert not hasattr(graph, "run_graph")
    assert not hasattr(graph, "GraphRun")

    node = importlib.import_module("maistro.graph.node")
    assert not hasattr(node, "NodeRun")

    executor = importlib.import_module("maistro.graph.executor")
    assert "run_graph" not in vars(executor)
    assert "GraphRun" not in vars(executor)

    events = importlib.import_module("maistro.graph.events")
    for factory in (
        "graph_started",
        "graph_completed",
        "graph_failed",
        "node_started",
        "node_completed",
        "node_failed",
        "node_retrying",
        "cycle_started",
    ):
        assert factory not in vars(events)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("maistro.graph.run")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("maistro.graph.strategy")
