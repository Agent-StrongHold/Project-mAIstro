"""New Hive Graph work requires the canonical spine, even in degraded mode (#1113)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from services import canonical_dag_runner as runner
from services import dag_agents
from services.dag_execution_scope import DagExecutionScope
from services.engine import EngineService


@pytest.fixture(params=["container", "run_store", "graph_run_store"])
def incomplete_spine(request):
    if request.param == "container":
        return None
    container = SimpleNamespace(
        run_store=SimpleNamespace(create_run=AsyncMock()), graph_run_store=object()
    )
    setattr(container, request.param, None)
    return container


@pytest.mark.parametrize("getter", ["get_run_store", "get_canonical_run_store"])
def test_graph_store_access_refuses_an_incomplete_spine(monkeypatch, incomplete_spine, getter):
    monkeypatch.setattr(dag_agents, "_container", lambda: incomplete_spine)
    with pytest.raises(RuntimeError, match="canonical graph execution spine is unavailable"):
        getattr(dag_agents, getter)()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["registered", "legacy"])
async def test_graph_admission_refuses_before_any_work(monkeypatch, incomplete_spine, surface):
    """No Run, configure hook, resolver, or executor is reached on refusal."""
    monkeypatch.setattr(dag_agents, "_container", lambda: incomplete_spine)
    monkeypatch.setattr(runner, "_container", lambda: incomplete_spine)
    traverse = AsyncMock(side_effect=AssertionError("execution reached without canonical spine"))
    monkeypatch.setattr(dag_agents, "run_durable_graph", traverse)
    monkeypatch.setattr(runner, "run_durable_graph", traverse)
    configure = Mock(side_effect=AssertionError("configure reached without canonical spine"))
    resolver = Mock(side_effect=AssertionError("resolver reached without canonical spine"))
    monkeypatch.setattr(dag_agents, "_resolve_nodes_with", resolver)
    monkeypatch.setattr(runner, "_resolver", resolver)

    with pytest.raises(RuntimeError, match="canonical graph execution spine is unavailable"):
        if surface == "registered":
            await dag_agents.run_registered_dag(
                "daily-status", workspace_id="ws", project_id="project", configure=configure
            )
        else:
            await runner.execute_dag(
                {"nodes": [{"id": "only", "role": "worker"}], "edges": []},
                scope=DagExecutionScope(workspace_id="ws", project_id="project", user_id="actor"),
            )
    configure.assert_not_called()
    resolver.assert_not_called()
    traverse.assert_not_awaited()
    if incomplete_spine is not None and incomplete_spine.run_store is not None:
        incomplete_spine.run_store.create_run.assert_not_awaited()


def test_engine_health_distinguishes_graph_execution_unavailability():
    engine = EngineService()
    assert engine.health()["graph_execution_available"] is False
    engine._agent_port = SimpleNamespace(
        container=SimpleNamespace(run_store=object(), graph_run_store=object())
    )
    assert engine.health()["graph_execution_available"] is True
    engine._agent_port.container.graph_run_store = None
    assert engine.health()["graph_execution_available"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["registered", "legacy"])
async def test_admitted_graph_recovers_after_sqlite_reconnect(monkeypatch, tmp_path, surface):
    """Two independent connections see one Run; a fresh owner recovers checkpoint zero."""
    import aiosqlite
    from services import legacy_dag_node
    from services.engine import get_engine
    from services.registered_dag_recovery import recover_stranded_registered_dag_runs

    from maistro.container import build_node_resolver
    from maistro.graph.durable_runs import CanonicalDurableRunStore, SqliteGraphContinuationStore
    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.runs.model import RunStatus
    from maistro.runs.sqlite_store import SqliteRunStore

    async def composition(conn):
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        runs = SqliteRunStore(conn, project_store=projects)
        await runs.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        return SimpleNamespace(
            run_store=runs,
            graph_run_store=CanonicalDurableRunStore(runs, continuations),
            projects=projects,
            event_bus=None,
        )

    class ProcessDied(BaseException):
        pass

    admitted = []

    async def crash_before_checkpoint(_graph, **kwargs):
        admitted.append(kwargs["run_id"])
        raise ProcessDied

    def fake_model(_on_response=None):
        async def complete(_messages, **_kwargs):
            return "hermetic result"

        return complete

    monkeypatch.setattr(legacy_dag_node, "_build_llm_call", fake_model)
    monkeypatch.setattr(dag_agents, "_resolve_nodes_with", lambda **_kwargs: build_node_resolver())
    # The recovery module captured its import; keep its resolver equally hermetic.
    monkeypatch.setattr("services.registered_dag_recovery._resolve_nodes_with", build_node_resolver)
    registry = dag_agents.get_registry()
    dag_id = "canonical-restart-proof"
    registry.register(
        {
            "id": dag_id,
            "name": dag_id,
            "entry_node": "a",
            "nodes": [
                {"id": name, "kind": "transform.alias_keys", "config": {"mapping": {}}}
                for name in ("a", "b")
            ],
            "edges": [{"from_node": "a", "to_node": "b"}],
        }
    )
    db = tmp_path / "canonical-graph.db"
    try:
        async with aiosqlite.connect(db) as first, aiosqlite.connect(db) as replica:
            owner = await composition(first)
            root = await owner.projects.create_root("restart-workspace")
            monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=owner))
            with monkeypatch.context() as crash_patch:
                module = dag_agents if surface == "registered" else runner
                crash_patch.setattr(module, "run_durable_graph", crash_before_checkpoint)
                with pytest.raises(ProcessDied):
                    if surface == "registered":
                        await dag_agents.run_registered_dag(
                            dag_id,
                            workspace_id=root.workspace_id,
                            project_id=root.project_id,
                            user_id="restart-actor",
                            provenance={"admission_source": "schedule"},
                        )
                    else:
                        await runner.execute_dag(
                            {
                                "id": dag_id,
                                "nodes": [
                                    {
                                        "id": "a",
                                        "role": "worker",
                                        "config": {"execution_tier": "safe"},
                                    }
                                ],
                                "edges": [],
                            },
                            scope=DagExecutionScope(
                                workspace_id=root.workspace_id,
                                project_id=root.project_id,
                                user_id="restart-actor",
                            ),
                            execution_mode="interactive",
                        )
            observer = await composition(replica)
            saved = await observer.run_store.get_run(admitted[0])
            assert saved.status is RunStatus.QUEUED
            assert saved.actor_principal_id == "restart-actor"
            assert await observer.graph_run_store.get(admitted[0]) is None
        # No original connection survives. The recovery seam reconstructs from persisted facts.
        async with aiosqlite.connect(db) as fresh:
            restarted = await composition(fresh)
            monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=restarted))
            recover = (
                recover_stranded_registered_dag_runs
                if surface == "registered"
                else runner.recover_stranded_dag_runs
            )
            assert await recover() == 1
            record = await restarted.graph_run_store.get(admitted[0])
            assert record.run.status is RunStatus.COMPLETED
            assert record.run.actor_principal_id == "restart-actor"
            assert record.run.workspace_id == root.workspace_id
            assert record.run.project_id == root.project_id
            assert record.node_runs and record.attempts
            assert {node.run_id for node in record.node_runs} == {admitted[0]}
            assert await recover() == 0
    finally:
        registry.deregister(dag_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("live", [False, True])
async def test_shipped_stream_refuses_without_a_spine(monkeypatch, incomplete_spine, live):
    from services.graph_runner import execute_dag_streaming

    monkeypatch.setattr(runner, "_container", lambda: incomplete_spine)
    traverse = AsyncMock(side_effect=AssertionError("must not traverse"))
    projection = AsyncMock()
    monkeypatch.setattr(runner, "run_durable_graph", traverse)
    frames = [
        frame
        async for frame in execute_dag_streaming(
            {"id": "unavailable", "nodes": [{"id": "only", "role": "worker"}], "edges": []},
            scope=DagExecutionScope(workspace_id="ws", project_id="project", user_id="actor"),
            on_event=AsyncMock(return_value=1) if live else None,
            on_result=projection,
        )
    ]
    assert frames[-1] == {
        "status": "failed",
        "error": "CanonicalGraphUnavailable: execution failed; see server logs",
    }
    assert not any(frame["status"] == "completed" or frame.get("run_id") for frame in frames)
    traverse.assert_not_awaited()
    projection.assert_not_awaited()


def test_shipped_http_refuses_without_a_spine(monkeypatch, admin_client):
    import stores

    monkeypatch.setattr(runner, "_container", lambda: None)
    traverse = AsyncMock(side_effect=AssertionError("must not traverse"))
    monkeypatch.setattr(runner, "run_durable_graph", traverse)
    workspace = admin_client.post(
        "/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": "No Graph spine"}
    )
    assert workspace.status_code == 201
    dag_id = "http-unavailable-spine"
    stores.dags[dag_id] = {
        "id": dag_id,
        "name": dag_id,
        "nodes": [{"id": "only", "role": "worker"}],
        "edges": [],
    }
    try:
        response = admin_client.post(
            f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace.json()["id"]}
        )
        assert response.json() == {
            "status": "failed",
            "error": "CanonicalGraphUnavailable: execution failed; see server logs",
        }
        traverse.assert_not_awaited()
    finally:
        stores.dags.pop(dag_id, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["registered", "legacy"])
async def test_failed_canonical_admission_never_falls_back(
    monkeypatch, canonical_graph_spine, surface
):
    monkeypatch.setattr(
        canonical_graph_spine.run_store,
        "create_run",
        AsyncMock(side_effect=OSError("store unavailable")),
    )
    module = dag_agents if surface == "registered" else runner
    traverse = AsyncMock(side_effect=AssertionError("must not traverse"))
    monkeypatch.setattr(module, "run_durable_graph", traverse)
    with pytest.raises(OSError, match="store unavailable"):
        if surface == "registered":
            await dag_agents.run_registered_dag(
                "daily-status",
                workspace_id="test-workspace",
                project_id=canonical_graph_spine.project_id,
            )
        else:
            await runner.execute_dag(
                {"nodes": [{"id": "only", "role": "worker"}], "edges": []},
                scope=DagExecutionScope(
                    workspace_id="test-workspace",
                    project_id=canonical_graph_spine.project_id,
                    user_id="actor",
                ),
            )
    traverse.assert_not_awaited()
