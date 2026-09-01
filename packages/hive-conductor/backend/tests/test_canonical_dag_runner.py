"""Behavioral proof for #835's Conductor DAG convergence seam."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph.durable_runs import InMemoryDurableRunStore


def _safe_node(node_id: str, *, prompt: str | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": node_id,
        "role": "worker",
        "prompt": prompt or node_id,
        "config": {"execution_tier": "safe"},
    }


def _fake_llm_builder(*, fail_prompt: str | None = None):
    def build(_on_response: Any = None):
        async def call(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
            system = str(messages[0]["content"])
            if fail_prompt and fail_prompt in system:
                raise RuntimeError("intentional node failure")
            return f"ok:{system}"

        return call

    return build


def test_graph_normalizes_crud_and_substrate_edge_dialects() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    common = [_safe_node("a"), _safe_node("b")]
    crud = graph_from_legacy_dag(
        {
            "id": "crud",
            "nodes": common,
            "edges": [{"id": "e1", "from_node": "a", "to_node": "b"}],
        },
        workspace_id="w",
        project_id="p",
    )
    substrate = graph_from_legacy_dag(
        {
            "id": "substrate",
            "nodes": common,
            "edges": [{"id": "e1", "source": "a", "target": "b"}],
        },
        workspace_id="w",
        project_id="p",
    )

    assert [(edge.from_node, edge.to_node) for edge in crud.edges] == [("a", "b")]
    assert [(edge.from_node, edge.to_node) for edge in substrate.edges] == [("a", "b")]
    assert crud.metadata["entry_node"] == "a"
    assert substrate.metadata["entry_node"] == "a"


def test_empty_dag_cannot_report_success_with_zero_work() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    with pytest.raises(ValueError, match="no nodes"):
        graph_from_legacy_dag(
            {"id": "empty", "nodes": [], "edges": []},
            workspace_id="w",
            project_id="p",
        )


def test_cycle_is_rejected_before_execution() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    with pytest.raises(ValueError, match="cyclic DAG"):
        graph_from_legacy_dag(
            {
                "id": "cycle",
                "nodes": [_safe_node("a"), _safe_node("b")],
                "edges": [
                    {"id": "ab", "from_node": "a", "to_node": "b"},
                    {"id": "ba", "from_node": "b", "to_node": "a"},
                ],
            },
            workspace_id="w",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_required_node_failure_terminalizes_canonical_run_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_dag_runner as runner

    store = InMemoryDurableRunStore()
    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: store)

    result = await runner.execute_dag(
        {
            "id": "failure",
            "name": "failure",
            "nodes": [_safe_node("a", prompt="fail-me")],
            "edges": [],
        },
        llm_builder=_fake_llm_builder(fail_prompt="fail-me"),
    )

    assert result["status"] == "failed"
    assert result["run_id"]
    assert result["node_results"]["a"]["success"] is False
    record = await store.get(result["run_id"])
    assert record is not None
    assert record.run.status.value == "failed"


@pytest.mark.asyncio
async def test_fanout_runs_under_one_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_dag_runner as runner

    store = InMemoryDurableRunStore()
    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: store)

    result = await runner.execute_dag(
        {
            "id": "fanout",
            "name": "fanout",
            "entry_node": "root",
            "nodes": [_safe_node("root"), _safe_node("left"), _safe_node("right")],
            "edges": [
                {"id": "left", "from_node": "root", "to_node": "left"},
                {"id": "right", "from_node": "root", "to_node": "right"},
            ],
        },
        llm_builder=_fake_llm_builder(),
    )

    assert result["status"] == "completed"
    assert set(result["node_results"]) == {"root", "left", "right"}
    assert all(node["success"] for node in result["node_results"].values())
    record = await store.get(result["run_id"])
    assert record is not None
    assert {node_run.node_id for node_run in record.node_runs} == {"root", "left", "right"}
    assert {node_run.run_id for node_run in record.node_runs} == {result["run_id"]}


@pytest.mark.asyncio
async def test_legacy_facade_cannot_return_failed_run_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.graph_runner as facade

    async def failed(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "failed",
            "run_id": "run-failed",
            "error": "node failed",
            "node_results": {"a": {"success": False, "response": "node failed"}},
        }

    monkeypatch.setattr(facade, "_canonical_execute_dag", failed)

    with pytest.raises(facade.CanonicalDagExecutionError, match="node failed") as captured:
        await facade.execute_dag({"nodes": [_safe_node("a")], "edges": []})

    assert captured.value.result["run_id"] == "run-failed"
