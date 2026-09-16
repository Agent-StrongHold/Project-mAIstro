"""Adversarial semantic-parity evidence for legacy Conductor DAG conditions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def _canonical_test_container() -> tuple[Any, Any]:
    from maistro.graph.durable_runs import (
        CanonicalDurableRunStore,
        InMemoryGraphContinuationStore,
    )
    from maistro.runs import InMemoryRunStore

    class _Projects:
        async def get(self, project_id: str) -> Any:
            return SimpleNamespace(project_id=project_id, workspace_id="w")

        async def root_for_workspace(self, workspace_id: str) -> Any:
            return SimpleNamespace(project_id="root-project", workspace_id=workspace_id)

    run_store = InMemoryRunStore(project_store=_Projects())
    graph_store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    return (
        SimpleNamespace(
            config=SimpleNamespace(workspace_id="w"),
            project_scope_store=_Projects(),
            run_store=run_store,
            graph_run_store=graph_store,
        ),
        graph_store,
    )


def _safe_node(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": node_id,
        "role": "worker",
        "prompt": node_id,
        "config": {"execution_tier": "safe"},
    }


def _fake_llm_builder(_on_response: Any = None):
    async def call(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
        return f"ok:{messages[0]['content']}"

    return call


def test_arbitrary_legacy_condition_remains_an_unconditional_dependency() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    graph = graph_from_legacy_dag(
        {
            "id": "legacy-label",
            "nodes": [_safe_node("a"), _safe_node("b")],
            "edges": [
                {
                    "id": "ab",
                    "from_node": "a",
                    "to_node": "b",
                    "condition": "if x",
                }
            ],
        },
        workspace_id="w",
        project_id="p",
    )

    assert graph.edges[0].condition is None
    assert graph.edges[0].metadata["legacy_condition"] == "if x"


def test_natural_language_with_an_operator_is_not_mistaken_for_a_predicate() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    graph = graph_from_legacy_dag(
        {
            "id": "legacy-label-with-operator",
            "nodes": [_safe_node("a"), _safe_node("b")],
            "edges": [
                {
                    "id": "ab",
                    "from_node": "a",
                    "to_node": "b",
                    "condition": "if x == y",
                }
            ],
        },
        workspace_id="w",
        project_id="p",
    )

    assert graph.edges[0].condition is None
    assert graph.edges[0].metadata["legacy_condition"] == "if x == y"


@pytest.mark.asyncio
async def test_arbitrary_legacy_condition_cannot_silently_skip_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_dag_runner as runner
    import services.dag_agents as dag_agents

    container, store = _canonical_test_container()
    monkeypatch.setattr(runner, "_container", lambda: container)
    monkeypatch.setattr(dag_agents, "_container", lambda: container)
    monkeypatch.setattr(runner, "get_run_store", lambda: store)

    result = await runner.execute_dag(
        {
            "id": "legacy-condition-execution",
            "name": "legacy-condition-execution",
            "nodes": [_safe_node("a"), _safe_node("b")],
            "edges": [
                {
                    "id": "ab",
                    "from_node": "a",
                    "to_node": "b",
                    "condition": "if x",
                }
            ],
        },
        llm_builder=_fake_llm_builder,
    )

    assert result["status"] == "completed"
    assert set(result["node_results"]) == {"a", "b"}
    assert result["node_results"]["a"]["success"] is True
    assert result["node_results"]["b"]["success"] is True
