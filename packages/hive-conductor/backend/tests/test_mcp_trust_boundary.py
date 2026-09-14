from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.mcp_client import AtlassianMCPClient, MCPAuthorizationError  # noqa: E402

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
