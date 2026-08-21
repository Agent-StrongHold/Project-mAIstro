"""Default MCP catalog — aligned with this repo's MCP server manifests."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from models.schemas import MCPServer, MCPTool

# SECURITY-REVIEW: remote MCP endpoint; auth via env/credentials vault (never commit tokens).
ATLASSIAN_ROVO_MCP_URL = os.getenv(
    "ATLASSIAN_ROVO_MCP_URL",
    "https://mcp.atlassian.com/v1/mcp/authv2",
).strip()

ATLASSIAN_ROVO_SERVER_ID = "mcp-atlassian-rovo"
FILESYSTEM_SERVER_ID = "mcp-filesystem-local"
FILESYSTEM_MCP_URL = os.getenv("FILESYSTEM_MCP_URL", "http://127.0.0.1:9999/mcp").strip()

ATLASSIAN_ROVO_TOOLS: tuple[dict[str, str], ...] = (
    {
        "name": "jira_search",
        "description": "Search Jira issues and projects (Rovo MCP)",
        "category": "jira",
    },
    {
        "name": "jira_get_issue",
        "description": "Fetch a Jira issue by key (Rovo MCP)",
        "category": "jira",
    },
    {
        "name": "jira_create_issue",
        "description": "Create a Jira story, bug, or task (gated in Hive UI)",
        "category": "jira",
    },
    {
        "name": "jira_update_issue",
        "description": "Update Jira fields and status (Rovo MCP)",
        "category": "jira",
    },
    {
        "name": "confluence_search",
        "description": "Search Confluence pages and spaces (Rovo MCP)",
        "category": "confluence",
    },
    {
        "name": "confluence_get_page",
        "description": "Read a Confluence page by id or title (Rovo MCP)",
        "category": "confluence",
    },
    {
        "name": "confluence_create_page",
        "description": "Create a Confluence page (Rovo MCP)",
        "category": "confluence",
    },
    {
        "name": "confluence_update_page",
        "description": "Update Confluence page content (Rovo MCP)",
        "category": "confluence",
    },
)

FILESYSTEM_TOOLS: tuple[dict[str, str], ...] = (
    {"name": "read_file", "description": "Read a UTF-8 file", "category": "filesystem"},
    {"name": "list_dir", "description": "List directory entries", "category": "filesystem"},
    {"name": "search_files", "description": "Search files by glob", "category": "filesystem"},
    {"name": "write_file", "description": "Write a UTF-8 file", "category": "filesystem"},
    {
        "name": "run_command",
        "description": "Run an approved shell command",
        "category": "filesystem",
    },
    {
        "name": "get_env",
        "description": "Read allowlisted environment variables",
        "category": "filesystem",
    },
)


def is_atlassian_rovo_url(url: str) -> bool:
    return "mcp.atlassian.com" in (url or "")


def atlassian_rovo_server(*, now: datetime | None = None) -> MCPServer:
    t = now or datetime.now(UTC)
    return MCPServer(
        id=ATLASSIAN_ROVO_SERVER_ID,
        name="Atlassian Rovo MCP",
        description=(
            "Cloud MCP for Jira and Confluence. Configure token via Credentials or "
            "ATLASSIAN_API_TOKEN + ATLASSIAN_SITE_URL in the container."
        ),
        url=ATLASSIAN_ROVO_MCP_URL,
        status="connecting",
        tools_count=len(ATLASSIAN_ROVO_TOOLS),
        last_ping=t,
        version="rovo-mcp",
        capabilities=["jira", "confluence", "compass"],
    )


def filesystem_local_server(*, now: datetime | None = None) -> MCPServer:
    t = now or datetime.now(UTC)
    return MCPServer(
        id=FILESYSTEM_SERVER_ID,
        name="Filesystem",
        description="Local workspace tools (loopback MCP sidecar in sandbox)",
        url=FILESYSTEM_MCP_URL,
        status="disconnected",
        tools_count=len(FILESYSTEM_TOOLS),
        last_ping=t,
        version="0.4.0",
        capabilities=["tools"],
    )


def _tools_for_server(
    server_id: str, specs: tuple[dict[str, str], ...], prefix: str
) -> list[MCPTool]:
    tools: list[MCPTool] = []
    for idx, spec in enumerate(specs, start=1):
        tools.append(
            MCPTool(
                id=f"{prefix}-t-{idx}",
                server_id=server_id,
                name=spec["name"],
                description=spec["description"],
                input_schema={"type": "object", "properties": {}},
                category=spec.get("category"),
            )
        )
    return tools


def atlassian_rovo_tools() -> list[MCPTool]:
    return _tools_for_server(ATLASSIAN_ROVO_SERVER_ID, ATLASSIAN_ROVO_TOOLS, "rovo")


def filesystem_local_tools() -> list[MCPTool]:
    return _tools_for_server(FILESYSTEM_SERVER_ID, FILESYSTEM_TOOLS, "fs")


def platform_mcp_catalog() -> tuple[list[MCPServer], list[MCPTool]]:
    """Built-in servers (always seeded).

    NOTE: filesystem-local is NOT seeded by default — the sidecar isn't
    deployed in any current environment, and surfacing it in the MCP
    list with a permanent "disconnected" state was confusing users
    (task #29). The server + tool helpers are kept so a future deploy
    that DOES ship the sidecar can opt in via merge_manifest_catalog().
    """
    servers = [atlassian_rovo_server()]
    tools = atlassian_rovo_tools()
    return servers, tools


def merge_manifest_catalog(
    servers: list[MCPServer],
    tools: list[MCPTool],
) -> tuple[list[MCPServer], list[MCPTool]]:
    """Overlay MAISTROJSON manifests when the repo layout is present."""
    try:
        from services.mcp_manifest_loader import load_manifest_files
    except ImportError:
        return servers, tools

    by_id = {s.id: s for s in servers}
    tool_ids = {t.id for t in tools}
    merged_tools = list(tools)

    for raw in load_manifest_files():
        sid = str(raw.get("id", ""))
        if not sid:
            continue
        if sid not in by_id:
            by_id[sid] = MCPServer(
                id=sid,
                name=str(raw.get("name", sid)),
                description=str(raw.get("description", "")),
                url=str(raw.get("url", "")),
                status="connecting",
                tools_count=len(raw.get("tools") or []),
                last_ping=datetime.now(UTC),
                version=str(raw.get("version")) if raw.get("version") else None,
                capabilities=list(raw.get("capabilities") or []),
            )
        else:
            existing = by_id[sid]
            by_id[sid] = existing.model_copy(
                update={
                    "name": raw.get("name", existing.name),
                    "description": raw.get("description", existing.description),
                    "url": raw.get("url", existing.url),
                    "version": raw.get("version", existing.version),
                    "capabilities": raw.get("capabilities", existing.capabilities),
                }
            )
        for idx, spec in enumerate(raw.get("tools") or [], start=1):
            if not isinstance(spec, dict):
                continue
            tid = f"{sid}-m-{idx}"
            if tid in tool_ids:
                continue
            merged_tools.append(
                MCPTool(
                    id=tid,
                    server_id=sid,
                    name=str(spec.get("name", "tool")),
                    description=str(spec.get("description", "")),
                    input_schema={"type": "object", "properties": {}},
                    category=spec.get("category"),
                )
            )
            tool_ids.add(tid)

    return list(by_id.values()), merged_tools
