"""Tests for the daily_status_runner service."""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import httpx
import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from services.dag_agents import _node_resolver  # noqa: E402
from services.daily_status_runner import (  # noqa: E402
    _get_registry,
    _inject_jira_credentials,
    _node_named,
    _result_to_jira_section,
    run_daily_status_dag,
)

from maistro.graph.definitions import Graph  # noqa: E402
from maistro.graph.template_adapter import (  # noqa: E402
    descriptor_to_template,
    snapshot_to_template,
)

# --- registry + canonical template projection ------------------------------


def _daily_status_graph(*, workspace_id: str = "w1", project_id: str = "p1") -> tuple[Any, Graph]:
    template = descriptor_to_template(
        _get_registry().get("daily-status"), workspace_id=workspace_id
    )
    return template, template.instantiate(project_id=project_id)


def test_get_registry_returns_same_instance_each_call() -> None:
    a = _get_registry()
    b = _get_registry()
    assert a is b
    assert "daily-status" in a


def test_registry_contains_daily_status_with_pm_use_case() -> None:
    reg = _get_registry()
    desc = reg.get("daily-status")
    assert desc is not None
    assert desc.use_case == "pm_fleet"
    assert desc.agent_id == "dag:daily-status"


def test_registry_descriptor_projects_to_canonical_template() -> None:
    template, _ = _daily_status_graph()
    assert template.template_id == "daily-status"
    assert template.version == 1
    assert template.workspace_id == "w1"
    assert template.metadata["entry_node"] == "jira_poll"
    assert [node.node_id for node in template.nodes][:2] == ["jira_poll", "jira_items_alias"]
    assert template.nodes[0].node_type == "jira.poll"
    assert template.nodes[1].parameters["mapping"] == {"items": "issues"}
    assert template.edges[0].from_node == "jira_poll"
    assert template.edges[0].to_node == "jira_items_alias"


def test_instantiated_graph_carries_template_provenance() -> None:
    template, graph = _daily_status_graph()
    assert graph.workspace_id == "w1"
    assert graph.project_id == "p1"
    assert graph.source_template is not None
    assert graph.source_template.template_id == "daily-status"
    assert graph.source_template.template_version == 1
    assert graph.source_template.template_hash == template.content_hash


def test_instantiation_remaps_entry_to_fresh_node_identity() -> None:
    template, graph = _daily_status_graph()
    template_ids = {node.node_id for node in template.nodes}
    instantiated_ids = {node.node_id for node in graph.nodes}
    assert template_ids.isdisjoint(instantiated_ids)
    jira_poll = _node_named(graph, "jira_poll")
    assert jira_poll is not None
    assert graph.metadata["entry_node"] == jira_poll.node_id


def test_inject_jira_credentials_mutates_jira_poll_node_only() -> None:
    template, graph = _daily_status_graph()
    _inject_jira_credentials(
        graph, pat="abc-pat", base_url="https://example.atlassian.net", flavor="cloud"
    )
    poll = _node_named(graph, "jira_poll")
    assert poll.inputs["pat"] == "abc-pat"
    assert poll.inputs["base_url"] == "https://example.atlassian.net"
    assert poll.inputs["flavor"] == "cloud"
    alias = _node_named(graph, "jira_items_alias")
    assert "pat" not in alias.inputs
    # Credentials land on the instantiated Graph only; the template that
    # provenance hashes stays secret-free.
    assert "abc-pat" not in template.model_dump_json()
    assert graph.source_template.template_hash == template.content_hash


def test_inject_credentials_without_jira_poll_is_noop() -> None:
    graph = Graph(workspace_id="w1", project_id="p1", name="empty")
    out = _inject_jira_credentials(graph, pat="x", base_url="y")
    assert out.nodes == []


# --- _node_resolver compatibility seam ------------------------------------


def test_node_resolver_returns_registered_node_by_id() -> None:
    dag = {"nodes": [{"id": "n1", "kind": "transform.alias_keys"}]}
    node = _node_resolver("n1", dag)
    assert type(node).__name__ == "TransformAliasKeysNode"


def test_node_resolver_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        _node_resolver("ghost", {"nodes": []})


def test_node_resolver_accepts_canonical_graph() -> None:
    snapshot = {
        "id": "g1",
        "name": "g1",
        "nodes": [{"id": "n1", "kind": "transform.alias_keys"}],
        "edges": [],
        "entry_node": "n1",
    }
    graph = snapshot_to_template(snapshot, workspace_id="w1").instantiate(project_id="p1")
    node = _node_resolver(graph.nodes[0].node_id, graph)
    assert type(node).__name__ == "TransformAliasKeysNode"


# --- _result_to_jira_section ----------------------------------------------


class _FakeRun:
    def __init__(self, error: str | None = None) -> None:
        self.error = error


class _FakeRecord:
    def __init__(
        self,
        status: Any,
        node_runs: list[Any],
        error: str | None = None,
    ) -> None:
        self.status = status
        self.node_runs = node_runs
        self.run = _FakeRun(error)


class _FakeNodeRun:
    def __init__(
        self,
        node_id: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.node_id = node_id
        self.result = result
        self.error = error


def _section_graph() -> Graph:
    _, graph = _daily_status_graph()
    return graph


def test_result_to_jira_section_completed_returns_ok_with_issues() -> None:
    from maistro.graph.durable_runs import RunStatus

    graph = _section_graph()
    jp_record = _FakeNodeRun(
        _node_named(graph, "jira_poll").node_id,
        result={
            "count": 2,
            "issues": [
                {
                    "key": "P-1",
                    "summary": "Ship X",
                    "status": "Done",
                    "updated": "t1",
                    "url": "https://jira.example.com/browse/P-1",
                },
                {
                    "key": "P-2",
                    "summary": "Hire Y",
                    "status": "Open",
                    "updated": "t2",
                    "url": "https://jira.example.com/browse/P-2",
                },
            ],
        },
    )
    filt_record = _FakeNodeRun(
        _node_named(graph, "jira_epic_filter").node_id, result={"kept": 1, "dropped": 1}
    )
    rec = _FakeRecord(RunStatus.COMPLETED, [jp_record, filt_record])
    section = _result_to_jira_section(
        rec, graph=graph, base_url="https://jira.example.com", flavor="server"
    )
    assert section["status"] == "ok"
    assert section["count"] == 2
    assert section["epics_kept"] == 1
    assert section["source"] == "dag:daily-status"
    assert section["flavor"] == "server"
    assert [item["key"] for item in section["issues"]] == ["P-1", "P-2"]


def test_result_to_jira_section_failed_permission_returns_auth_failed() -> None:
    from maistro.graph.durable_runs import RunStatus

    graph = _section_graph()
    jp_record = _FakeNodeRun(
        _node_named(graph, "jira_poll").node_id,
        error="PermissionError: jira_auth_failed status=401 base=https://jira.example.com",
    )
    rec = _FakeRecord(RunStatus.FAILED, [jp_record], error="PermissionError: propagated")
    section = _result_to_jira_section(
        rec, graph=graph, base_url="https://jira.example.com", flavor="server"
    )
    assert section["status"] == "auth_failed"
    assert "jira_auth_failed" in section["detail"]
    assert section["issues"] == []
    assert section["source"] == "dag:daily-status"


def test_result_to_jira_section_other_failure_returns_error() -> None:
    from maistro.graph.durable_runs import RunStatus

    graph = _section_graph()
    jp_record = _FakeNodeRun(
        _node_named(graph, "jira_poll").node_id,
        error="RuntimeError: jira_http_error status=500",
    )
    rec = _FakeRecord(RunStatus.FAILED, [jp_record], error="RuntimeError: propagated")
    section = _result_to_jira_section(rec, graph=graph, base_url="https://x", flavor="server")
    assert section["status"] == "error"
    assert section["issues"] == []
    assert section["detail"] == "RuntimeError: propagated"


def test_result_to_jira_section_missing_url_uses_constructed_browse_url() -> None:
    from maistro.graph.durable_runs import RunStatus

    graph = _section_graph()
    jp_record = _FakeNodeRun(
        _node_named(graph, "jira_poll").node_id,
        result={
            "count": 1,
            "issues": [{"key": "P-9", "summary": "x", "status": "Open"}],
        },
    )
    rec = _FakeRecord(RunStatus.COMPLETED, [jp_record])
    section = _result_to_jira_section(
        rec, graph=graph, base_url="https://jira.example.com/", flavor="server"
    )
    assert section["issues"][0]["url"] == "https://jira.example.com/browse/P-9"


# --- end-to-end run_daily_status_dag with httpx mocked --------------------


async def test_run_daily_status_dag_completes_with_mocked_jira(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_issues = {
        "issues": [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "Ship feature A",
                    "status": {"name": "In Progress"},
                    "updated": "2026-05-22T08:00:00Z",
                    "issuetype": {"name": "Epic"},
                },
            }
        ]
    }

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return fake_issues

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    section = await run_daily_status_dag(
        user_id="u1",
        workspace_id="w1",
        project_id="p1",
        pat="tk",
        base_url="https://jira.example.com",
        flavor="server",
    )
    assert section["status"] == "ok"
    assert section["count"] == 1
    assert section["epics_kept"] == 1
    assert section["source"] == "dag:daily-status"
    assert section["issues"][0]["key"] == "PROJ-1"
    assert section["flavor"] == "server"


async def test_run_daily_status_dag_401_returns_auth_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Resp:
        status_code = 401

        def json(self) -> Any:
            return {}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    section = await run_daily_status_dag(
        user_id="u1",
        project_id="p1",
        pat="bad",
        base_url="https://jira.example.com",
        flavor="server",
    )
    assert section["status"] == "auth_failed"
    assert section["issues"] == []


async def test_run_daily_status_dag_catches_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.daily_status_runner as runner

    async def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("synthetic boom")

    monkeypatch.setattr(runner, "run_registered_dag", _boom)
    section = await run_daily_status_dag(
        user_id="u1",
        project_id="p1",
        pat="tk",
        base_url="https://jira.example.com",
        flavor="server",
    )
    assert section["status"] == "error"
    assert "RuntimeError" in section["detail"]
    assert section["issues"] == []
