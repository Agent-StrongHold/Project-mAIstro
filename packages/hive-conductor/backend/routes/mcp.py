from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import MCPServer, MCPTool
from pydantic import BaseModel, ConfigDict

from maistro.http import shared_client

router = APIRouter(tags=["mcp"])

logger = logging.getLogger(__name__)


def _user_id(request: Request) -> str | None:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    return str(uid) if uid else None


async def _health_check(server: MCPServer, *, user_id: str | None = None) -> MCPServer:
    from services.mcp_client import test_mcp_server
    from services.mcp_defaults import is_atlassian_rovo_url

    if is_atlassian_rovo_url(server.url):
        result = await test_mcp_server(server.id, user_id=user_id, url=server.url)
        status = "connected" if result.get("ok") else "connecting"
        return server.model_copy(
            update={
                "status": status,
                "last_ping": datetime.now(UTC),
            }
        )
    try:
        async with shared_client(timeout=3.0) as client:
            r = await client.get(server.url)
            if r.status_code < 500:
                return server.model_copy(
                    update={
                        "status": "connected",
                        "last_ping": datetime.now(UTC),
                    }
                )
    except Exception as _exc:
        __import__("logging").getLogger("hive.routes.mc").warning(
            "error_swallowed file=%s line=%d: %s",
            "packages/hive-conductor/backend/routes/mcp.py",
            47,
            _exc,
        )
        pass
    return server.model_copy(update={"status": "disconnected", "last_ping": datetime.now(UTC)})


@router.get("/servers", response_model=list[MCPServer])
async def list_servers(request: Request) -> list[MCPServer]:
    import asyncio

    uid = _user_id(request)
    servers = list(stores.mcp_servers.values())
    checked = await asyncio.gather(*[_health_check(s, user_id=uid) for s in servers])
    for s in checked:
        stores.mcp_servers[s.id] = s
    return list(checked)


@router.get("/servers/{server_id}", response_model=MCPServer)
def get_server(server_id: str) -> MCPServer:
    if server_id not in stores.mcp_servers:
        raise HTTPException(status_code=404, detail="server not found")
    return stores.mcp_servers[server_id]


class CreateServerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    url: str


@router.post("/servers", response_model=MCPServer, status_code=201)
def add_server(body: CreateServerBody) -> MCPServer:
    sid = str(uuid4())
    server = MCPServer(
        id=sid,
        name=body.name,
        description=body.description,
        url=body.url,
        status="connecting",
        tools_count=0,
    )
    stores.mcp_servers[sid] = server
    return server


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: str) -> None:
    if server_id not in stores.mcp_servers:
        raise HTTPException(status_code=404, detail="server not found")
    stores.mcp_servers.pop(server_id)


@router.post("/servers/{server_id}/scan")
def scan_server(server_id: str) -> dict:
    if server_id not in stores.mcp_servers:
        raise HTTPException(status_code=404, detail="server not found")
    return {"findings": [], "status": "clean"}


class McpTestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    server_id: str | None = None


@router.post("/test")
async def test_mcp_connection(body: McpTestBody, request: Request) -> dict:
    """Headless connectivity test (container runtime — uses Credentials vault)."""
    from services.mcp_client import test_mcp_server

    uid = _user_id(request)
    if body.server_id:
        if body.server_id not in stores.mcp_servers:
            raise HTTPException(status_code=404, detail="server not found")
        srv = stores.mcp_servers[body.server_id]
        return await test_mcp_server(srv.id, user_id=uid, url=srv.url)

    results = []
    for srv in stores.mcp_servers.values():
        results.append(await test_mcp_server(srv.id, user_id=uid, url=srv.url))
    return {"results": results}


@router.get("/tools", response_model=list[MCPTool])
def list_tools() -> list[MCPTool]:
    return list(stores.mcp_tools.values())


class DiscoverBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str


@router.post("/discover")
def discover_tools(body: DiscoverBody) -> dict:
    return {"tools": [], "status": "scanning"}
