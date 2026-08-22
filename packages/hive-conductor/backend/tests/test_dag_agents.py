"""Tests for the shared DAG-as-agent execution service."""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from services.dag_agents import get_registry, run_registered_dag  # noqa: E402

from maistro.graph.durable_runs import RunStatus  # noqa: E402

_SYNTH_DAG = {
    "id": "synth-noop",
    "name": "Synth Noop",
    "description": "single alias node for execution tests",
    "entry_node": "only",
    "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
    "edges": [],
}


@pytest.fixture()
def synth_dag_id():
    registry = get_registry()
    registry.register(dict(_SYNTH_DAG))
    try:
        yield "synth-noop"
    finally:
        registry.deregister("synth-noop")


def test_get_registry_is_shared_and_seeded() -> None:
    a = get_registry()
    b = get_registry()
    assert a is b
    assert "daily-status" in a


def test_run_registered_dag_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        asyncio.run(run_registered_dag("no-such-dag", workspace_id="w1", project_id="p1"))


def test_run_registered_dag_produces_provenanced_completed_run(synth_dag_id: str) -> None:
    graph, record = asyncio.run(
        run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1", user_id="u1")
    )
    assert record.run.status is RunStatus.COMPLETED
    assert record.run.workspace_id == "w1"
    assert record.run.project_id == "p1"
    assert graph.source_template is not None
    assert graph.source_template.template_id == synth_dag_id
    # The Run's persisted Graph snapshot carries the same provenance.
    assert record.run.graph.materialize().source_template == graph.source_template


def test_configure_hook_touches_the_instantiated_graph_only(synth_dag_id: str) -> None:
    def configure(graph) -> None:
        graph.nodes[0].inputs["extra"] = "value"

    graph, record = asyncio.run(
        run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1", configure=configure)
    )
    assert graph.nodes[0].inputs["extra"] == "value"
    assert record.run.status is RunStatus.COMPLETED
    # The registered snapshot is untouched — a later run starts clean.
    graph_again, _ = asyncio.run(
        run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1")
    )
    assert "extra" not in graph_again.nodes[0].inputs
