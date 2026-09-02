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


def test_legacy_outcome_tokens_preserve_dependency_edge_behavior() -> None:
    """Bare evolution tokens were labels to the old wave runner, not predicates."""
    from services.canonical_dag_runner import graph_from_legacy_dag

    graph = graph_from_legacy_dag(
        {
            "id": "legacy-condition",
            "nodes": [_safe_node("a"), _safe_node("b")],
            "edges": [
                {
                    "id": "e1",
                    "from_node": "a",
                    "to_node": "b",
                    "condition": "success",
                }
            ],
        },
        workspace_id="w",
        project_id="p",
    )

    assert graph.edges[0].condition is None
    assert graph.edges[0].metadata["legacy_condition"] == "success"


def test_canonical_comparison_condition_is_preserved() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    graph = graph_from_legacy_dag(
        {
            "id": "predicate-condition",
            "nodes": [_safe_node("a"), _safe_node("b")],
            "edges": [
                {
                    "id": "e1",
                    "from_node": "a",
                    "to_node": "b",
                    "condition": "response == 'ready'",
                }
            ],
        },
        workspace_id="w",
        project_id="p",
    )

    assert graph.edges[0].condition == "response == 'ready'"
    assert graph.edges[0].metadata["legacy_condition"] == "response == 'ready'"


def test_run_scout_becomes_a_canonical_pre_entry_node() -> None:
    from services.canonical_dag_runner import graph_from_legacy_dag

    graph = graph_from_legacy_dag(
        {
            "id": "with-scout",
            "run_scout": True,
            "nodes": [_safe_node("entry")],
            "edges": [],
            "entry_node": "entry",
        },
        workspace_id="w",
        project_id="p",
    )

    assert graph.metadata["legacy_run_scout"] is True
    assert graph.metadata["entry_node"] == "__hive_legacy_scout__"
    assert {node.node_id for node in graph.nodes} == {"__hive_legacy_scout__", "entry"}
    assert [(edge.from_node, edge.to_node) for edge in graph.edges] == [
        ("__hive_legacy_scout__", "entry")
    ]


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
async def test_run_scout_executes_under_the_same_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_dag_runner as runner

    store = InMemoryDurableRunStore()
    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: store)

    result = await runner.execute_dag(
        {
            "id": "scouted-run",
            "name": "scouted-run",
            "run_scout": True,
            "entry_node": "entry",
            "nodes": [_safe_node("entry")],
            "edges": [],
        },
        llm_builder=_fake_llm_builder(),
    )

    assert result["status"] == "completed"
    assert set(result["node_results"]) == {"__hive_legacy_scout__", "entry"}
    record = await store.get(result["run_id"])
    assert record is not None
    assert [node_run.node_id for node_run in record.node_runs] == [
        "__hive_legacy_scout__",
        "entry",
    ]
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


# --- legacy shape validation ----------------------------------------------------


def _legacy_dag(nodes: list[Any], edges: list[Any] | Any = None, **extra: Any) -> dict[str, Any]:
    return {"id": "dag", "name": "dag", "nodes": nodes, "edges": edges or [], **extra}


@pytest.mark.parametrize(
    ("dag", "message"),
    [
        ({"nodes": ["not-an-object"], "edges": []}, "DAG node must be an object"),
        ({"nodes": [{"name": "anonymous"}], "edges": []}, "DAG node is missing id"),
        (
            {"nodes": [_safe_node("a"), _safe_node("a")], "edges": []},
            "duplicate DAG node id",
        ),
        ({"nodes": [_safe_node("a")], "edges": "not-a-list"}, "DAG edges must be a list"),
        ({"nodes": [_safe_node("a")], "edges": ["not-an-object"]}, "DAG edge must be an object"),
        (
            {
                "nodes": [_safe_node("a")],
                "edges": [{"id": "e", "from_node": "a", "to_node": "ghost"}],
            },
            "references node outside DAG",
        ),
        (
            {"nodes": [_safe_node("a")], "edges": [], "entry_node": "ghost"},
            "entry node 'ghost' does not exist",
        ),
        (
            {
                "nodes": [_safe_node("a"), _safe_node("b"), _safe_node("c")],
                "edges": [{"id": "ab", "from_node": "a", "to_node": "b"}],
            },
            "multiple disconnected entry roots",
        ),
        (
            {
                "nodes": [_safe_node("a"), _safe_node("b"), _safe_node("c")],
                "edges": [{"id": "bc", "from_node": "b", "to_node": "c"}],
                "entry_node": "a",
            },
            "unreachable from its entry node",
        ),
        (
            {"nodes": [_safe_node("__hive_legacy_scout__")], "edges": []},
            "is reserved for run_scout compatibility",
        ),
    ],
)
def test_invalid_legacy_shapes_are_rejected_before_a_run_exists(
    dag: dict[str, Any], message: str
) -> None:
    """Every admission-time rejection: a shape the adapter cannot represent
    faithfully must fail before any canonical Run/NodeRun identity is minted."""
    from services.canonical_dag_runner import graph_from_legacy_dag

    with pytest.raises(ValueError, match=message):
        graph_from_legacy_dag(dag, workspace_id="w", project_id="p")


@pytest.mark.asyncio
async def test_scope_resolves_the_default_workspace_and_its_root_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a live container, an unscoped legacy DAG is admitted into the
    configured workspace and the workspace's root project, not a compat scope."""
    import services.canonical_dag_runner as runner

    class _Config:
        workspace_id = "ws-configured"

    class _Root:
        project_id = "root-project"

    class _ScopeStore:
        async def root_for_workspace(self, workspace_id: str) -> _Root:
            return _Root()

    class _Container:
        config = _Config()
        project_scope_store = _ScopeStore()
        run_store = "the-canonical-run-store"

    monkeypatch.setattr(runner, "_container", lambda: _Container())

    workspace, project, run_store = await runner._scope({}, workspace_id=None, project_id=None)

    assert (workspace, project, run_store) == (
        "ws-configured",
        "root-project",
        "the-canonical-run-store",
    )


@pytest.mark.asyncio
async def test_scope_prefers_the_dag_declared_workspace_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_dag_runner as runner

    class _Config:
        workspace_id = "ws-configured"

    class _ScopeStore:
        async def root_for_workspace(self, workspace_id: str) -> Any:  # pragma: no cover
            raise AssertionError("a declared project must not consult the root scope")

    class _Container:
        config = _Config()
        project_scope_store = _ScopeStore()
        run_store = "the-canonical-run-store"

    monkeypatch.setattr(runner, "_container", lambda: _Container())

    workspace, project, _ = await runner._scope(
        {"workspace_id": "ws-declared", "project_id": "p-declared"},
        workspace_id=None,
        project_id=None,
    )

    assert (workspace, project) == ("ws-declared", "p-declared")


def test_request_credentials_reach_nodes_as_scoped_env_keys() -> None:
    """The legacy adapter consumed USER_CRED_* env keys; admission must still
    forward request-time credentials under that contract without persisting
    them into Run provenance."""
    from services.canonical_dag_runner import _node_env

    env = _node_env(
        {"id": "dag-1"},
        user_id="user-1",
        user_credentials={"api_token": "tok-42"},
    )

    assert env["USER_CRED_API_TOKEN"] == "tok-42"
    assert env["DAG_USER_ID"] == "user-1"
    assert env["DAG_ID"] == "dag-1"


def test_the_resolver_names_a_node_missing_from_the_adapter_map() -> None:
    """Durable recovery cannot invent a node the admission snapshot never
    carried; the failure must name both the node and the map."""
    from services.canonical_dag_runner import _resolver

    resolve = _resolver(
        {},
        task_desc="t",
        node_env={},
        execution_mode="interactive",
        on_response=None,
        llm_builder=None,
    )

    with pytest.raises(KeyError, match="missing from adapter map"):
        resolve("ghost", None)


def test_recovery_refuses_a_run_whose_nodes_lack_durable_legacy_metadata() -> None:
    """A Run admitted by some other seam has no legacy node facts to rebuild
    from; guessing defaults here would execute work nobody admitted."""
    from services.canonical_dag_runner import _recovery_resolver

    from maistro.graph.definitions import Graph, Node
    from maistro.runs.model import GraphSnapshot, Run, RunStatus

    plain = Graph(
        workspace_id="ws-1",
        project_id="p-1",
        name="not-a-legacy-dag",
        nodes=[Node(node_id="n1", node_type="noop", name="n1", metadata={})],
        edges=[],
    )
    run = Run(
        run_id="run-plain",
        workspace_id="ws-1",
        project_id="p-1",
        graph=GraphSnapshot.from_graph(plain),
        status=RunStatus.QUEUED,
        provenance={"admission_source": "hive_legacy_dag", "execution_mode": "interactive"},
    )

    with pytest.raises(ValueError, match="lacks durable legacy_node metadata"):
        _recovery_resolver(run)


@pytest.mark.asyncio
async def test_a_metrics_recording_failure_never_fails_the_completed_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Node metrics are a projection of the Run, never a co-owner of its
    outcome: a broken ingest logs and the canonical truth still returns."""
    import logging

    import services.canonical_dag_runner as runner

    store = InMemoryDurableRunStore()
    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: store)

    def _metrics_down(_record: Any) -> int:
        raise RuntimeError("metrics store unavailable")

    monkeypatch.setattr(runner, "record_run_completion", _metrics_down)

    with caplog.at_level(logging.WARNING, logger=runner.logger.name):
        result = await runner.execute_dag(
            _legacy_dag(nodes=[_safe_node("a")]),
            llm_builder=_fake_llm_builder(),
        )

    assert result["status"] == "completed"
    assert result["run_id"]
    assert any("node_metrics_not_recorded" in record.message for record in caplog.records)
