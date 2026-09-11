from __future__ import annotations

import importlib

import pytest


def test_pre_durable_executor_is_not_a_graph_public_surface() -> None:
    """Graph work enters through durable_runs, never the retired executor."""
    graph = importlib.import_module("maistro.graph")

    assert not hasattr(graph, "run_graph")
    assert not hasattr(graph, "GraphRun")

    executor = importlib.import_module("maistro.graph.executor")
    assert "run_graph" not in vars(executor)
    assert "GraphRun" not in vars(executor)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("maistro.graph.run")
