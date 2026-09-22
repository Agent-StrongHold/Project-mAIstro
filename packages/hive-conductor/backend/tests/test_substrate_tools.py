"""Coverage for substrate_tools.py's DAG-execution-scope authorization seam (#766).

`tool_run_workflow` and `tool_hill_climb` resolve a DagExecutionScope before
calling `execute_dag` — the same canonical Workspace/Project authorization
boundary the DAG-run HTTP and WebSocket routes take (see
`test_dag_execution_scope.py`). An unauthorized/unknown workspace selection
is a refusal here too, never a silent legacy-scope fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest


async def _workspace(workspace_id: str, *, member_user_id: str) -> None:
    from hive_conductor.models.workspace import WorkspacePresentation
    from hive_conductor.services.workspace_authority import (
        canonical_store_for_tests,
        presentation_store,
    )

    store = canonical_store_for_tests()
    await store.create(creator_user_id=member_user_id, workspace_id=workspace_id, name=workspace_id)
    presentation_store()[workspace_id] = WorkspacePresentation(
        workspace_id=workspace_id,
        persona_template_id="test-persona",
        active=True,
        updated_at=datetime.now(UTC),
    )


def _dag(dag_id: str, *, node_id: str = "n1") -> dict[str, Any]:
    return {
        "id": dag_id,
        "name": "substrate-test",
        "nodes": [{"id": node_id, "role": "worker", "name": "Worker", "prompt": "hi"}],
        "edges": [],
        "eval_rubric": {"criteria": [{"name": "quality", "weight": 100}]},
    }


@pytest.mark.asyncio
async def test_tool_run_workflow_executes_through_an_authorized_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hive_conductor.services.graph_runner as graph_runner
    import hive_conductor.stores as stores
    from hive_conductor.services.substrate_tools import tool_run_workflow

    dag_id = f"substrate-run-{uuid4()}"
    stores.dags[dag_id] = _dag(dag_id)
    await _workspace("substrate-run-ws", member_user_id="u1")

    async def fake_execute(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "completed",
            "node_results": {"n1": {"role": "worker", "success": True, "response": "ok"}},
        }

    monkeypatch.setattr(graph_runner, "execute_dag", fake_execute)

    result = await tool_run_workflow(
        {"dag_id": dag_id, "workspace_id": "substrate-run-ws"}, user_id="u1"
    )

    assert result["status"] == "completed"
    assert result["dag_id"] == dag_id
    assert result["nodes_succeeded"] == 1


@pytest.mark.asyncio
async def test_tool_run_workflow_refuses_an_unauthorized_workspace() -> None:
    import hive_conductor.stores as stores
    from hive_conductor.services.dag_execution_scope import DagWorkspaceSelectionError
    from hive_conductor.services.substrate_tools import tool_run_workflow

    dag_id = f"substrate-refuse-{uuid4()}"
    stores.dags[dag_id] = _dag(dag_id)

    with pytest.raises(DagWorkspaceSelectionError):
        await tool_run_workflow(
            {"dag_id": dag_id, "workspace_id": "no-such-workspace"}, user_id="u1"
        )


@pytest.mark.asyncio
async def test_tool_hill_climb_executes_each_attempt_through_the_authorized_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hive_conductor.services.graph_runner as graph_runner
    import hive_conductor.services.substrate_tools as substrate_tools
    import hive_conductor.stores as stores

    dag_id = f"substrate-climb-{uuid4()}"
    stores.dags[dag_id] = _dag(dag_id)
    await _workspace("substrate-climb-ws", member_user_id="u1")

    async def fake_execute(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "node_results": {"n1": {"role": "worker", "success": True, "response": "the output"}},
        }

    async def fake_evaluate(_args: Any, _user_id: str) -> dict[str, Any]:
        return {"dag_id": dag_id, "eval": {"total": 95, "critique": ""}}

    monkeypatch.setattr(graph_runner, "execute_dag", fake_execute)
    monkeypatch.setattr(substrate_tools, "tool_evaluate_run", fake_evaluate)

    result = await substrate_tools.tool_hill_climb(
        {"dag_id": dag_id, "workspace_id": "substrate-climb-ws", "target_score": 90},
        user_id="u1",
    )

    assert result["passed"] is True
    assert result["best_score"] == 95
    assert len(result["attempts"]) == 1


@pytest.mark.asyncio
async def test_tool_hill_climb_refuses_an_unauthorized_workspace() -> None:
    import hive_conductor.stores as stores
    from hive_conductor.services.dag_execution_scope import DagWorkspaceSelectionError
    from hive_conductor.services.substrate_tools import tool_hill_climb

    dag_id = f"substrate-climb-refuse-{uuid4()}"
    stores.dags[dag_id] = _dag(dag_id)

    with pytest.raises(DagWorkspaceSelectionError):
        await tool_hill_climb({"dag_id": dag_id, "workspace_id": "no-such-workspace"}, user_id="u1")
