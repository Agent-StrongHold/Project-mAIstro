from __future__ import annotations

import contextlib
import pathlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import services.mcp_client as mcp_client_module  # noqa: E402
import services.mcp_defaults as mcp_defaults_module  # noqa: E402
from services.mcp_client import (  # noqa: E402
    AtlassianMCPClient,
    MCPAuthorizationError,
    _normalize_mcp_url,
)

from maistro.capabilities.binding import Binding  # noqa: E402


def _binding(*tools: str) -> Binding:
    return Binding(
        workspace_id="workspace-1",
        project_id="project-1",
        capability="mcp",
        config={"server_id": "mcp-atlassian-rovo", "allowed_tools": list(tools)},
    )


@pytest.mark.asyncio
async def test_arbitrary_tool_name_is_denied_before_pat_lookup() -> None:
    client = AtlassianMCPClient(user_id="user-1", binding=_binding("jira_search"))
    with pytest.raises(MCPAuthorizationError, match="not allowed"):
        await client.call_tool("delete_everything", {})


@pytest.mark.asyncio
async def test_mcp_without_binding_is_denied() -> None:
    client = AtlassianMCPClient(user_id="user-1", binding=None)
    with pytest.raises(MCPAuthorizationError, match="canonical Binding"):
        await client.call_tool("jira_search", {})


def test_binding_allowlist_is_finite_and_exact() -> None:
    client = AtlassianMCPClient(user_id="user-1", binding=_binding("jira_search"))
    client._authorize("jira_search")
    with pytest.raises(MCPAuthorizationError):
        client._authorize("jira_search_extra")


def _fake_binding_config(config: Any) -> Any:
    """A Binding-shaped object whose ``config`` is not the strict model dict."""
    return SimpleNamespace(workspace_id="workspace-1", project_id="project-1", config=config)


def test_non_mapping_binding_config_yields_an_empty_allowlist() -> None:
    client = AtlassianMCPClient(user_id="user-1", binding=_fake_binding_config("oops"))
    with pytest.raises(MCPAuthorizationError, match="not allowed"):
        client._authorize("jira_search")


def test_malformed_allowlist_entries_are_dropped_not_trusted() -> None:
    # A string is not a list; a list entry that is not a non-empty string is
    # not a tool name. Both must collapse to an empty/filtered allowlist.
    client = AtlassianMCPClient(
        user_id="user-1", binding=_fake_binding_config({"allowed_tools": "jira_search"})
    )
    with pytest.raises(MCPAuthorizationError, match="not allowed"):
        client._authorize("jira_search")

    partial = AtlassianMCPClient(
        user_id="user-1",
        binding=_fake_binding_config({"allowed_tools": ["jira_search", 7, "", None]}),
    )
    partial._authorize("jira_search")
    with pytest.raises(MCPAuthorizationError):
        partial._authorize("jira_get_issue")


def test_binding_without_workspace_or_project_scope_is_denied() -> None:
    client = AtlassianMCPClient(
        user_id="user-1",
        binding=SimpleNamespace(
            workspace_id="", project_id="project-1", config={"allowed_tools": ["jira_search"]}
        ),
    )
    with pytest.raises(MCPAuthorizationError, match="Workspace/Project scope"):
        client._authorize("jira_search")


def test_binding_for_a_different_server_is_denied() -> None:
    client = AtlassianMCPClient(
        user_id="user-1",
        binding=_fake_binding_config(
            {"server_id": "mcp-filesystem-local", "allowed_tools": ["jira_search"]}
        ),
    )
    with pytest.raises(MCPAuthorizationError, match="not for the Atlassian server"):
        client._authorize("jira_search")


def test_non_atlassian_endpoint_is_never_configured() -> None:
    client = AtlassianMCPClient(
        user_id="user-1", binding=_binding("jira_search"), url="https://evil.example.com/v1/mcp"
    )
    assert client._url == ""


def test_endpoint_validation_failure_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str) -> bool:
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(mcp_defaults_module, "is_atlassian_rovo_url", _boom)
    assert _normalize_mcp_url("https://mcp.atlassian.com/v1/mcp/authv2") == ""


@pytest.mark.asyncio
async def test_call_tool_without_credential_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_client_module, "resolve_atlassian_token", lambda user_id: None)
    client = AtlassianMCPClient(user_id="user-1", binding=_binding("jira_search"))
    with pytest.raises(MCPAuthorizationError, match="No Atlassian credential"):
        await client.call_tool("jira_search", {})


@pytest.mark.asyncio
async def test_call_tool_with_invalid_endpoint_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_client_module, "resolve_atlassian_token", lambda user_id: "pat-123")
    client = AtlassianMCPClient(
        user_id="user-1", binding=_binding("jira_search"), url="https://evil.example.com/v1/mcp"
    )
    with pytest.raises(MCPAuthorizationError, match="Invalid Atlassian MCP endpoint"):
        await client.call_tool("jira_search", {})


@pytest.mark.asyncio
async def test_call_tool_happy_path_posts_only_the_allowlisted_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"ok": True, "id": "resp-1"}

    class _Client:
        async def post(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            json: Any = None,
        ) -> _Response:
            sent["url"] = url
            sent["headers"] = headers
            sent["json"] = json
            return _Response()

    @contextlib.asynccontextmanager
    async def _fake_shared_client(timeout: float | None = None) -> Any:
        yield _Client()

    monkeypatch.setattr(mcp_client_module, "shared_client", _fake_shared_client)
    monkeypatch.setattr(mcp_client_module, "resolve_atlassian_token", lambda user_id: "pat-123")

    client = AtlassianMCPClient(
        user_id="user-1",
        binding=_binding("jira_search"),
        url="https://mcp.atlassian.com/v1/mcp/authv2",
    )
    result = await client.call_tool("jira_search", {"jql": "project = X"})

    assert result == {"ok": True, "id": "resp-1"}
    assert sent["url"] == "https://mcp.atlassian.com/v1/mcp/authv2"
    assert sent["headers"] == {"Authorization": "Bearer pat-123"}
    assert sent["json"]["method"] == "tools/call"
    assert sent["json"]["params"]["name"] == "jira_search"
    assert sent["json"]["params"]["arguments"] == {"jql": "project = X"}
