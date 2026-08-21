"""Phase 1b: contract + integration tests for the 7 sync node kinds.

Each kind gets its own focused unit test. The final integration test
exercises the daily-report flow end-to-end:
    jira.poll → transform.filter_by_type[Epic] → transform.extract_field
              → transform.format_markdown → dashboard.append_section
…proving the catalog composes into a working pipeline without the
runtime executor (which is exercised by Phase 0d's existing graph tests).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maistro.graph.nodes import (
    NodeContext,
    catalog_json,
    get_node,
    list_kinds,
)


def _ctx(**overrides: Any) -> NodeContext:
    base = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "n1",
        "user_id": "u1",
        "project_id": "p1",
    }
    base.update(overrides)
    return NodeContext(**base)


# --- transform.extract_field ----------------------------------------------


async def test_extract_field_basic_dot_path() -> None:
    Node = get_node("transform.extract_field")
    out = await Node().run(
        {
            "items": [
                {"fields": {"summary": "Ship payments v2"}},
                {"fields": {"summary": "Onboard new vendor"}},
                {"fields": {}},
            ],
            "field_path": "fields.summary",
            "default": "—",
        },
        _ctx(),
    )
    assert out.success
    assert out.output.values == ["Ship payments v2", "Onboard new vendor", "—"]
    assert out.output.count == 3


# --- transform.filter_by_type ---------------------------------------------


async def test_filter_by_type_keeps_only_epics() -> None:
    Node = get_node("transform.filter_by_type")
    out = await Node().run(
        {
            "items": [
                {"key": "P-1", "fields": {"issuetype": {"name": "Epic"}}},
                {"key": "P-2", "fields": {"issuetype": {"name": "Story"}}},
                {"key": "P-3", "fields": {"issuetype": {"name": "epic"}}},  # case-insensitive
                {"key": "P-4", "fields": {"issuetype": None}},  # missing
            ],
            "types": ["Epic"],
        },
        _ctx(),
    )
    assert out.success
    kept_keys = [it["key"] for it in out.output.items]
    assert kept_keys == ["P-1", "P-3"]
    assert out.output.kept == 2
    assert out.output.dropped == 2


# --- transform.format_markdown --------------------------------------------


async def test_format_markdown_renders_template_with_dot_paths() -> None:
    Node = get_node("transform.format_markdown")
    out = await Node().run(
        {
            "items": [
                {"key": "P-1", "fields": {"summary": "Ship payments"}},
                {"key": "P-2", "fields": {"summary": "Hire designer"}},
            ],
            "template": "- {key}: {fields.summary}",
            "header": "## Epics updated in the last 24h",
        },
        _ctx(),
    )
    assert out.success
    assert "## Epics updated" in out.output.markdown
    assert "- P-1: Ship payments" in out.output.markdown
    assert "- P-2: Hire designer" in out.output.markdown
    assert out.output.rows_rendered == 2


async def test_format_markdown_empty_uses_fallback() -> None:
    Node = get_node("transform.format_markdown")
    out = await Node().run({"items": [], "template": "- {x}", "header": "## Things"}, _ctx())
    assert out.success
    assert "## Things" in out.output.markdown
    assert "_no items_" in out.output.markdown


# --- jira.poll (httpx mocked) ---------------------------------------------


@pytest.fixture
def fake_jira_server(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch httpx.AsyncClient so jira.poll thinks on-prem Jira Server returned
    an Epic + a Story. Records the auth header so the test can assert it."""
    state: dict[str, Any] = {"headers_seen": None, "auth_seen": None}

    response_payload = {
        "issues": [
            {
                "key": "P-100",
                "fields": {
                    "summary": "Migrate auth to MyID",
                    "status": {"name": "In Progress"},
                    "updated": "2026-05-22T08:00:00.000+0000",
                    "issuetype": {"name": "Epic"},
                },
            },
            {
                "key": "P-101",
                "fields": {
                    "summary": "Audit lockfile",
                    "status": {"name": "Done"},
                    "updated": "2026-05-22T07:00:00.000+0000",
                    "issuetype": {"name": "Story"},
                },
            },
        ]
    }

    class _FakeResp:
        status_code = 200

        def json(self) -> Any:
            return response_payload

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(
            self,
            url: str,
            *,
            params: dict | None = None,
            headers: dict | None = None,
            auth: Any = None,
        ) -> _FakeResp:
            state["url"] = url
            state["params"] = params
            state["headers_seen"] = headers
            state["auth_seen"] = auth
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return state


async def test_jira_poll_server_flavor_uses_bearer_pat(fake_jira_server: dict[str, Any]) -> None:
    Node = get_node("jira.poll")
    out = await Node().run(
        {
            "base_url": "https://jira.example.com",
            "jql": "updated >= -24h AND assignee = currentUser()",
            "pat": "secret-pat-value",
            "flavor": "server",
        },
        _ctx(),
    )
    assert out.success
    assert out.output.count == 2
    assert out.output.flavor == "server"
    assert out.output.issues[0].key == "P-100"
    assert out.output.issues[0].issuetype == "Epic"
    assert out.output.issues[0].url == "https://jira.example.com/browse/P-100"
    # Server flavor must use Authorization: Bearer; no basic-auth tuple
    assert fake_jira_server["headers_seen"]["Authorization"] == "Bearer secret-pat-value"
    assert fake_jira_server["auth_seen"] is None
    # API path is REST v2 for Server
    assert "/rest/api/2/search" in fake_jira_server["url"]


async def test_jira_poll_cloud_with_email_uses_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {"issues": []}

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(
            self,
            url: str,
            *,
            params: dict | None = None,
            headers: dict | None = None,
            auth: Any = None,
        ) -> _Resp:
            seen["url"] = url
            seen["auth"] = auth
            seen["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    Node = get_node("jira.poll")
    out = await Node().run(
        {
            "base_url": "https://acme.atlassian.net",
            "jql": "assignee=currentUser()",
            "pat": "cloud-token",
            "flavor": "cloud",
            "email": "alice@example.com",
        },
        _ctx(),
    )
    assert out.success
    assert seen["auth"] == ("alice@example.com", "cloud-token")
    # No Authorization header when using Basic auth
    assert "Authorization" not in seen["headers"]
    assert "/rest/api/3/search" in seen["url"]


async def test_jira_poll_401_surfaces_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 401

        def json(self) -> Any:
            return {"error": "unauthorized"}

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, *args: Any, **kwargs: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    Node = get_node("jira.poll")
    out = await Node().run(
        {
            "base_url": "https://jira.example.com",
            "jql": "x",
            "pat": "bad-pat",
            "flavor": "server",
        },
        _ctx(),
    )
    # The auth failure is caught by BaseNode.run and wrapped as a structured
    # failure — error_code lets the optimizer drop trust on this edge.
    assert out.success is False
    assert out.status == "failed"
    assert out.error_code == "PermissionError"
    assert "jira_auth_failed" in (out.error_message or "")


# --- airtable.poll --------------------------------------------------------


async def test_airtable_poll_uses_filter_formula_for_since_iso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {
                "records": [
                    {
                        "id": "rec1",
                        "fields": {"Name": "Alpha"},
                        "createdTime": "2026-05-22T07:00:00Z",
                    },
                ]
            }

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(
            self,
            url: str,
            *,
            params: dict | None = None,
            headers: dict | None = None,
            auth: Any = None,
        ) -> _Resp:
            seen["url"] = url
            seen["params"] = params
            seen["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    Node = get_node("airtable.poll")
    out = await Node().run(
        {
            "pat": "pat-token",
            "base_id": "appXYZ",
            "table": "Initiatives",
            "since_iso": "2026-05-21T00:00:00Z",
        },
        _ctx(),
    )
    assert out.success
    assert out.output.count == 1
    assert seen["headers"]["Authorization"] == "Bearer pat-token"
    assert "IS_AFTER(LAST_MODIFIED_TIME()" in seen["params"]["filterByFormula"]


# --- llm.summarize (httpx mocked against LLM gateway shape) -------------


async def test_llm_summarize_against_litellm_response_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")

    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {
                "model": "gemini-3.1-flash-lite",
                "choices": [{"message": {"content": "- shipped X\n- blocked on Y"}}],
                "usage": {"prompt_tokens": 1500, "completion_tokens": 80},
            }

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def post(self, url: str, *, json: Any = None, headers: Any = None) -> _Resp:
            seen["url"] = url
            seen["body"] = json
            seen["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    Node = get_node("llm.summarize")
    out = await Node().run(
        {"text": "lots of fleet activity ...", "style": "bullet", "max_tokens": 256},
        _ctx(),
    )
    assert out.success
    assert "shipped X" in out.output.summary
    assert out.output.tokens_in == 1500
    assert out.output.tokens_out == 80
    assert out.output.model_used == "gemini-3.1-flash-lite"
    # Verify the request shape (MAISTRO / LiteLLM-compatible)
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["body"]["model"] == "gemini-3.1-flash-lite"
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["max_tokens"] == 256
    assert seen["headers"]["Authorization"] == "Bearer fake-key"


# --- dashboard.append_section ---------------------------------------------


async def test_dashboard_append_section_appends_to_blackboard() -> None:
    from maistro.graph.types import GraphBlackboard

    bb = GraphBlackboard(task_objective="Daily report", workspace="")
    ctx = NodeContext(
        run_id="r1",
        dag_id="d1",
        node_id="n1",
        user_id="u1",
        project_id="p1",
        blackboard=bb,
    )

    Node = get_node("dashboard.append_section")
    out1 = await Node().run(
        {
            "dashboard_id": "daily-status",
            "section_title": "Jira (last 24h)",
            "markdown": "- P-100: Migrate auth\n- P-101: Audit lockfile",
            "order_hint": 1,
        },
        ctx,
    )
    assert out1.success
    assert out1.output.sections_total == 1

    out2 = await Node().run(
        {
            "dashboard_id": "daily-status",
            "section_title": "Airtable (last 24h)",
            "markdown": "- Alpha updated",
            "order_hint": 2,
        },
        ctx,
    )
    assert out2.output.sections_total == 2

    dashboard = bb.metadata.get("dashboard:daily-status")
    assert dashboard is not None
    titles = [s["title"] for s in dashboard["sections"]]
    assert titles == ["Jira (last 24h)", "Airtable (last 24h)"]


async def test_dashboard_upsert_does_not_duplicate_on_rerun() -> None:
    from maistro.graph.types import GraphBlackboard

    bb = GraphBlackboard(task_objective="x", workspace="")
    ctx = NodeContext(run_id="r1", dag_id="d1", node_id="n1", blackboard=bb)
    Node = get_node("dashboard.append_section")
    payload = {
        "dashboard_id": "x",
        "section_title": "S1",
        "markdown": "v1",
    }
    out1 = await Node().run(payload, ctx)
    payload["markdown"] = "v2"
    out2 = await Node().run(payload, ctx)
    assert out1.output.sections_total == 1
    assert out2.output.sections_total == 1  # upserted, not duplicated
    section = bb.metadata["dashboard:x"]["sections"][0]
    assert section["markdown"] == "v2"


# --- End-to-end: the daily-report flow composed by hand -------------------


async def test_daily_report_flow_e2e_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stitch jira.poll → filter_by_type[Epic] → extract_field → format_markdown
    → dashboard.append_section. Verifies the catalog composes into the
    daily-status DAG shape we'll seed in Phase 4 — no LLM involved (the LLM
    summary is a parallel branch tested separately above)."""

    fake_payload = {
        "issues": [
            {
                "key": "P-100",
                "fields": {
                    "summary": "Migrate auth",
                    "status": {"name": "In Progress"},
                    "updated": "2026-05-22T08:00:00Z",
                    "issuetype": {"name": "Epic"},
                },
            },
            {
                "key": "P-101",
                "fields": {
                    "summary": "Audit lockfile",
                    "status": {"name": "Done"},
                    "updated": "2026-05-22T07:00:00Z",
                    "issuetype": {"name": "Story"},
                },
            },
            {
                "key": "P-102",
                "fields": {
                    "summary": "VendorOnboard",
                    "status": {"name": "Open"},
                    "updated": "2026-05-22T06:00:00Z",
                    "issuetype": {"name": "Epic"},
                },
            },
        ]
    }

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return fake_payload

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, *args: Any, **kwargs: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    from maistro.graph.types import GraphBlackboard

    bb = GraphBlackboard(task_objective="Daily Status", workspace="")
    ctx = NodeContext(
        run_id="r1",
        dag_id="daily-status",
        node_id="entry",
        user_id="u1",
        project_id="p1",
        blackboard=bb,
    )

    # 1. jira.poll
    jp = await get_node("jira.poll")().run(
        {
            "base_url": "https://jira.example.com",
            "jql": "updated >= -24h AND assignee = currentUser()",
            "pat": "test-pat",
            "flavor": "server",
        },
        ctx,
    )
    assert jp.success
    assert jp.output.count == 3

    # 2. filter to Epics
    fbt = await get_node("transform.filter_by_type")().run(
        {
            "items": [i.model_dump() for i in jp.output.issues],
            "types": ["Epic"],
            "type_path": "issuetype",  # we flattened during poll output
        },
        ctx,
    )
    assert fbt.success
    assert fbt.output.kept == 2

    # 3. extract summaries
    ef = await get_node("transform.extract_field")().run(
        {
            "items": fbt.output.items,
            "field_path": "summary",
        },
        ctx,
    )
    assert ef.success
    assert ef.output.values == ["Migrate auth", "VendorOnboard"]

    # 4. format markdown
    fm = await get_node("transform.format_markdown")().run(
        {
            "items": fbt.output.items,
            "template": "- {key}: {summary} ({status})",
            "header": "## Epics updated (last 24h)",
        },
        ctx,
    )
    assert fm.success
    assert "P-100" in fm.output.markdown
    assert "Migrate auth (In Progress)" in fm.output.markdown
    assert "P-102" in fm.output.markdown

    # 5. dashboard append
    da = await get_node("dashboard.append_section")().run(
        {
            "dashboard_id": "daily-status",
            "section_title": "Jira Epics (last 24h)",
            "markdown": fm.output.markdown,
            "order_hint": 1,
        },
        ctx,
    )
    assert da.success

    # The complete dashboard, lifted from the blackboard, is exactly what
    # the Phase 4 daily-report route will emit.
    dashboard = bb.metadata["dashboard:daily-status"]
    assert len(dashboard["sections"]) == 1
    assert "P-100" in dashboard["sections"][0]["markdown"]


# --- Registry presence ----------------------------------------------------


def test_phase1b_catalog_has_seven_sync_kinds() -> None:
    kinds = list_kinds()
    expected = {
        "jira.poll",
        "airtable.poll",
        "transform.extract_field",
        "transform.filter_by_type",
        "transform.format_markdown",
        "llm.summarize",
        "dashboard.append_section",
    }
    missing = expected - set(kinds)
    assert not missing, f"missing kinds: {missing}"


def test_phase1b_catalog_serialization_is_jsonable() -> None:
    cat = catalog_json()
    # Must be plain-JSON-serializable for the frontend palette.
    json.dumps(cat)
    # Every entry has the fields the UI requires.
    for entry in cat:
        for required in (
            "kind",
            "kind_category",
            "display_name",
            "description",
            "cost_hint",
            "idempotent",
            "external_io",
            "input_schema",
            "output_schema",
        ):
            assert required in entry, f"{entry['kind']} missing {required}"
