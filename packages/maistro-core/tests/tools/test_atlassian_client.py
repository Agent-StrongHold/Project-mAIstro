"""Tests for AtlassianMCPClient's response-shaping and error-code logic.

Covers both Jira parsing (previously untested — pm_runner tests monkeypatch
past it) and the new Confluence parsing + cause-specific AtlassianMCPError
fields.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.tools.atlassian.client import AtlassianMCPClient, AtlassianMCPError


class _FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


class _FakeAsyncClient:
    def __init__(
        self, response: _FakeResponse | None = None, *, raise_exc: Exception | None = None
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> _FakeResponse:
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._response is not None
        return self._response

    async def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._response is not None
        return self._response


def _patch_http(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> None:
    monkeypatch.setattr(
        "maistro.tools.atlassian.client.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response),
    )


def _patch_http_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    monkeypatch.setattr(
        "maistro.tools.atlassian.client.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(raise_exc=exc),
    )


# ---------------------------------------------------------------------------
# Jira parsing
# ---------------------------------------------------------------------------


def test_parse_jira_issue_flattens_nested_fields() -> None:
    raw = {
        "key": "ENG-101",
        "self": "https://jira.example.com/rest/api/2/issue/101",
        "fields": {
            "summary": "Fix the thing",
            "status": {"name": "In Progress"},
            "assignee": {"displayName": "Jane Doe"},
            "issuetype": {"name": "Bug"},
            "labels": ["urgent", "backend"],
            "description": "x" * 5000,
        },
    }
    issue = AtlassianMCPClient._parse_jira_issue(raw)
    assert issue.key == "ENG-101"
    assert issue.summary == "Fix the thing"
    assert issue.status == "In Progress"
    assert issue.assignee == "Jane Doe"
    assert issue.issuetype == "Bug"
    assert issue.labels == ("urgent", "backend")
    assert len(issue.description) == 2000  # truncated, not dumped raw


def test_parse_jira_search_tolerates_issues_key() -> None:
    raw = {"issues": [{"key": "A-1", "fields": {"summary": "one"}}], "total": 1}
    result = AtlassianMCPClient._parse_jira_search(raw, jql="project = A")
    assert result.total == 1
    assert result.issues[0].key == "A-1"


# ---------------------------------------------------------------------------
# Confluence parsing
# ---------------------------------------------------------------------------


def test_parse_confluence_page_flattens_nested_body() -> None:
    raw = {
        "id": "123",
        "title": "Runbook",
        "space": {"key": "ENG"},
        "_links": {"webui": "/spaces/ENG/pages/123"},
        "body": {"storage": {"value": "<p>Steps...</p>"}},
    }
    page = AtlassianMCPClient._parse_confluence_page(raw)
    assert page.id == "123"
    assert page.title == "Runbook"
    assert page.space == "ENG"
    assert page.content == "<p>Steps...</p>"
    assert page.url == "/spaces/ENG/pages/123"


def test_parse_confluence_page_truncates_long_content() -> None:
    raw = {"id": "1", "title": "T", "body": "x" * 10_000}
    page = AtlassianMCPClient._parse_confluence_page(raw)
    assert len(page.content) == 4000


def test_parse_confluence_search_tolerates_results_key() -> None:
    raw = {
        "results": [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}],
        "total": 2,
    }
    result = AtlassianMCPClient._parse_confluence_search(raw, query="foo")
    assert result.total == 2
    assert [p.title for p in result.pages] == ["A", "B"]


@pytest.mark.asyncio
async def test_confluence_get_page_returns_flattened_page(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"id": "55", "title": "Onboarding", "body": "Welcome."},
    }
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    page = await client.confluence_get_page("55", confluence_pat="pat")
    assert page.id == "55"
    assert page.title == "Onboarding"
    assert page.content == "Welcome."


# ---------------------------------------------------------------------------
# Cause-specific error fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_401_is_not_recoverable_and_suggests_pat_regen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, _FakeResponse(401, text="Unauthorized"))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.call_tool("jira_get_issue", {"issue_key": "X-1"}, jira_pat="pat")
    err = exc_info.value
    assert err.error_code == "atlassian_http_error"
    assert err.recoverable is False
    assert "regenerate" in err.suggested_action.lower()


@pytest.mark.asyncio
async def test_call_tool_500_is_recoverable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, _FakeResponse(500, text="boom"))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.call_tool("jira_get_issue", {"issue_key": "X-1"}, jira_pat="pat")
    err = exc_info.value
    assert err.error_code == "atlassian_http_error"
    assert err.recoverable is True


@pytest.mark.asyncio
async def test_call_tool_non_json_response_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, _FakeResponse(200, json_data=None, text="<html>not json</html>"))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.call_tool("jira_get_issue", {"issue_key": "X-1"}, jira_pat="pat")
    assert exc_info.value.error_code == "atlassian_invalid_response"


@pytest.mark.asyncio
async def test_call_tool_transport_error_raises_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http_raises(monkeypatch, httpx.ConnectError("connection refused"))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.call_tool("jira_get_issue", {"issue_key": "X-1"}, jira_pat="pat")
    err = exc_info.value
    assert err.error_code == "atlassian_unreachable"
    assert "transport error" in str(err)


@pytest.mark.asyncio
async def test_call_tool_mcp_level_error_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "error": {"message": "invalid JQL", "code": -32602}}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.call_tool("jira_search_issues", {"jql": "bad"}, jira_pat="pat")
    err = exc_info.value
    assert err.error_code == "atlassian_tool_error"
    assert "invalid JQL" in str(err)


@pytest.mark.asyncio
async def test_call_tool_result_non_dict_wraps_in_raw_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": ["a", "b"]}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    result = await client.call_tool("jira_get_issue", {"issue_key": "X-1"}, jira_pat="pat")
    assert result == {"raw": ["a", "b"]}


# ---------------------------------------------------------------------------
# healthz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz_success_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, _FakeResponse(200, json_data={"status": "ok"}))
    client = AtlassianMCPClient()
    result = await client.healthz()
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_healthz_non_json_response_falls_back_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, _FakeResponse(200, json_data=None, text="OK"))
    client = AtlassianMCPClient()
    result = await client.healthz()
    assert result == {"status": "OK"}


@pytest.mark.asyncio
async def test_healthz_transport_error_raises_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http_raises(monkeypatch, httpx.ConnectError("refused"))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.healthz()
    assert exc_info.value.error_code == "atlassian_unreachable"


@pytest.mark.asyncio
async def test_healthz_http_error_status_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, _FakeResponse(503, text="down"))
    client = AtlassianMCPClient()
    with pytest.raises(AtlassianMCPError) as exc_info:
        await client.healthz()
    assert exc_info.value.error_code == "atlassian_http_error"


def test_health_url_strips_trailing_mcp_segment() -> None:
    client = AtlassianMCPClient(mcp_url="https://example.com/mcp")
    assert client.health_url == "https://example.com/healthz"


def test_health_url_without_mcp_segment_appends_healthz() -> None:
    client = AtlassianMCPClient(mcp_url="https://example.com")
    assert client.health_url == "https://example.com/healthz"


# ---------------------------------------------------------------------------
# Convenience wrapper methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_search_issues_returns_parsed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"issues": [{"key": "A-1", "fields": {"summary": "one"}}], "total": 1},
    }
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    result = await client.jira_search_issues("project = A", jira_pat="pat")
    assert result.jql == "project = A"
    assert result.issues[0].key == "A-1"


@pytest.mark.asyncio
async def test_jira_search_by_text_includes_project_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"issues": [], "total": 0}}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    result = await client.jira_search_by_text("bug report", project="ENG", jira_pat="pat")
    assert result.jql == 'text ~ "bug report"'


@pytest.mark.asyncio
async def test_jira_search_by_text_without_project(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"issues": [], "total": 0}}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    result = await client.jira_search_by_text("bug report", jira_pat="pat")
    assert result.total == 0


@pytest.mark.asyncio
async def test_jira_get_my_issues_uses_current_user_jql(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"issues": [], "total": 0}}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    result = await client.jira_get_my_issues(jira_pat="pat")
    assert result.jql == "assignee = currentUser() OR reporter = currentUser()"


@pytest.mark.asyncio
async def test_jira_get_issue_unwraps_issue_key(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"issue": {"key": "A-1", "fields": {"summary": "one"}}},
    }
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    issue = await client.jira_get_issue("A-1", jira_pat="pat")
    assert issue.key == "A-1"


@pytest.mark.asyncio
async def test_jira_get_issue_unwraps_content_list(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"key": "A-2", "fields": {"summary": "two"}}]},
    }
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    issue = await client.jira_get_issue("A-2", jira_pat="pat")
    assert issue.key == "A-2"


@pytest.mark.asyncio
async def test_jira_get_issue_falls_back_to_empty_dict_when_not_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"issue": "not a dict or list"}}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    issue = await client.jira_get_issue("A-3", jira_pat="pat")
    assert issue.key == ""


@pytest.mark.asyncio
async def test_confluence_search_returns_parsed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"results": [{"id": "1", "title": "A"}], "total": 1},
    }
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    result = await client.confluence_search("foo", confluence_pat="pat")
    assert result.query == "foo"
    assert result.pages[0].title == "A"


@pytest.mark.asyncio
async def test_confluence_get_page_unwraps_content_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"id": "9", "title": "Listed"}]},
    }
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    page = await client.confluence_get_page("9", confluence_pat="pat")
    assert page.id == "9"


@pytest.mark.asyncio
async def test_confluence_get_page_falls_back_to_empty_dict_when_not_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"page": "not a dict or list"}}
    _patch_http(monkeypatch, _FakeResponse(200, json_data=payload))
    client = AtlassianMCPClient()
    page = await client.confluence_get_page("x", confluence_pat="pat")
    assert page.id == ""


# ---------------------------------------------------------------------------
# Parsing edge cases — non-list shapes ignored
# ---------------------------------------------------------------------------


def test_parse_jira_search_ignores_non_list_issues() -> None:
    raw = {"issues": "not a list"}
    result = AtlassianMCPClient._parse_jira_search(raw, jql="x")
    assert result.issues == ()
    assert result.total == 0


def test_parse_confluence_search_ignores_non_list_pages() -> None:
    raw = {"results": "not a list"}
    result = AtlassianMCPClient._parse_confluence_search(raw, query="x")
    assert result.pages == ()
    assert result.total == 0


def test_headers_includes_both_pats_when_provided() -> None:
    client = AtlassianMCPClient()
    headers = client._headers("jira-pat", "confluence-pat")
    assert headers["X-Atlassian-Jira-Personal-Token"] == "jira-pat"
    assert headers["X-Atlassian-Confluence-Personal-Token"] == "confluence-pat"


def test_headers_omits_pats_when_not_provided() -> None:
    client = AtlassianMCPClient()
    headers = client._headers(None, None)
    assert "X-Atlassian-Jira-Personal-Token" not in headers
    assert "X-Atlassian-Confluence-Personal-Token" not in headers


def test_resolve_mcp_url_defaults_when_no_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLASSIAN_MCP_URL", raising=False)
    monkeypatch.delenv("ATLASSIAN_SERVER_MCP_URL", raising=False)
    client = AtlassianMCPClient()
    assert client.mcp_url == "http://atlassian-mcp:8000/mcp"


def test_resolve_mcp_url_prefers_atlassian_mcp_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_MCP_URL", "https://primary.example.com/mcp")
    monkeypatch.setenv("ATLASSIAN_SERVER_MCP_URL", "https://fallback.example.com/mcp")
    client = AtlassianMCPClient()
    assert client.mcp_url == "https://primary.example.com/mcp"


def test_to_dict_methods_produce_expected_shape() -> None:
    from maistro.tools.atlassian.client import ConfluencePage

    search = AtlassianMCPClient._parse_jira_search({"issues": [], "total": 0}, jql="x")
    page = ConfluencePage(id="1", title="t")
    assert search.to_dict()["jql"] == "x"
    assert page.to_dict()["id"] == "1"


def test_confluence_search_result_to_dict_includes_pages() -> None:
    confluence_result = AtlassianMCPClient._parse_confluence_search(
        {"results": [{"id": "1", "title": "A"}], "total": 1}, query="foo"
    )
    d = confluence_result.to_dict()
    assert d["query"] == "foo"
    assert d["pages"][0]["id"] == "1"
